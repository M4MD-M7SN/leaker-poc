"""
smart_txt_extractor.py — Adaptive Parser for Noisy Data Dumps
==============================================================

PROBLEM
-------
Real-world data dumps are messy and can contain ANY kind of PII — not just
emails and passwords.  A file might look like:

    # Breach: retailsite.com  |  date: 2022-07-14
    # columns: first_name|last_name|email|phone|address|username|password
    -----------------------------------------------
    John|Doe|john.doe@gmail.com|+14155551234|123 Main St|johnd|Passw0rd!
    // record below is partial
    Jane|Smith|jane@yahoo.com|5559876543||jsmith|hunter2
    -----------------------------------------------
    # Additional notes …

A naive reader breaks on the header block, separator lines, and inline
comments.  This extractor handles all of it.

HOW IT WORKS
------------
  Pass 1 — Classify every line as: DATA | COMMENT | SEPARATOR | BLANK

  Pass 2 — Sample DATA lines to auto-detect:
              • Combo separator  (: ; | \\t ,)
              • Most common field count
              • Semantic labels for each column by inspecting real values

  Pass 3 — Yield clean LeakerRecord objects:
              • Combo rows  → source_type="combo" (full row + per-field records)
              • Comment lines → source_type="txt_meta" (still searchable)
              • Malformed rows → source_type="combo_malformed" (not silently dropped)
              • Plain lines → source_type="txt"

FIELD TYPE DETECTION
--------------------
  The value classifier recognises these types (checked in order):
    email        — user@domain.tld
    ip_address   — IPv4 (1.2.3.4) or IPv6
    url          — http/https/ftp prefix
    credit_card  — 13–19 consecutive digits (Luhn-adjacent pattern)
    ssn          — XXX-XX-XXXX
    hash         — MD5/SHA1/SHA256/SHA512 hex  OR  bcrypt/unix crypt
    phone        — digits with optional +/dash/parens/dots, 7–15 digits total
    date         — YYYY-MM-DD, MM/DD/YYYY, DD-MM-YYYY, DD.MM.YYYY
    postal_code  — 5-digit US zip or short alphanumeric postal
    user_id      — purely numeric, short
    username     — short alphanumeric+symbols, no spaces
    name         — one or two capitalised words
    address      — mixed alpha+digits with spaces (street-like)
    password     — default for short opaque strings

COMBO LAYOUT DETECTION
----------------------
  A table of known real-world layouts maps field_count → candidate label
  sequences.  The best-scoring sequence (by matching classifier output)
  is chosen.  For unusual field counts or novel layouts the classifier
  falls back to generic  col_0, col_1, …  labels.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Generator

from .base import BaseExtractor, LeakerRecord


# ══════════════════════════════════════════════════════════════════════════════
# 1. LINE CLASSIFIERS
# ══════════════════════════════════════════════════════════════════════════════

_COMMENT_RE = re.compile(
    r"^\s*(#|//|--|/\*|\*/|;|rem\b)",
    re.IGNORECASE,
)

_SEPARATOR_RE = re.compile(r"^\s*[-=*_~+]{3,}\s*$")


# ══════════════════════════════════════════════════════════════════════════════
# 2. FIELD VALUE PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

# ── Email ──────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9_.+\-]{1,64}@[a-zA-Z0-9\-]{1,63}\.[a-zA-Z]{2,}$"
)

# ── IP addresses ───────────────────────────────────────────────────────────────
_IPV4_RE = re.compile(
    r"^((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
_IPV6_RE = re.compile(r"^[0-9a-fA-F:]{7,39}$")   # loose — full check below

# ── URL ────────────────────────────────────────────────────────────────────────
_URL_RE = re.compile(r"^(https?|ftp)://\S+", re.IGNORECASE)

# ── Credit card: 13-19 digits, possibly spaced/dashed ─────────────────────────
_CC_RAW_RE  = re.compile(r"^\d{13,19}$")
_CC_FMT_RE  = re.compile(r"^[\d][\d\- ]{11,21}[\d]$")

# ── SSN ────────────────────────────────────────────────────────────────────────
_SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")

# ── Hex hashes: MD5(32) SHA1(40) SHA224(56) SHA256(64) SHA384(96) SHA512(128) ─
_HASH_HEX_RE    = re.compile(r"^[0-9a-fA-F]+$")
_HASH_LENGTHS   = {32, 40, 56, 64, 96, 128}

# Bcrypt / unix-crypt
_HASH_CRYPT_RE  = re.compile(r"^\$(2[aby]?|1|5|6|argon2|sha256)\$.+")

# NTLM / LM hashes are 32 hex chars — already caught above

# ── Phone ──────────────────────────────────────────────────────────────────────
# Strips formatting, checks digit count 7–15
_PHONE_STRIP_RE = re.compile(r"[\s\-\.\(\)\/]")
_PHONE_CORE_RE  = re.compile(r"^\+?[0-9]{7,15}$")

# ── Date ───────────────────────────────────────────────────────────────────────
_DATE_RE = re.compile(
    r"^("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|"      # YYYY-MM-DD
    r"\d{1,2}[-/]\d{1,2}[-/]\d{4}|"      # MM/DD/YYYY or DD/MM/YYYY
    r"\d{1,2}\.\d{1,2}\.\d{4}|"          # DD.MM.YYYY
    r"\d{4}\d{2}\d{2}"                   # YYYYMMDD
    r")$"
)

# ── Postal / zip code ──────────────────────────────────────────────────────────
_ZIP_US_RE      = re.compile(r"^\d{5}(-\d{4})?$")
_POSTAL_INT_RE  = re.compile(r"^[A-Z0-9]{3,8}$", re.IGNORECASE)

# ── Numeric ID (user_id, record ID …) ─────────────────────────────────────────
_NUMERIC_ID_RE  = re.compile(r"^\d{1,20}$")

# ── Name (one or two capitalised words) ───────────────────────────────────────
_NAME_RE = re.compile(r"^[A-Z][a-z'\-]{1,30}(\s[A-Z][a-z'\-]{1,30})?$")

# ── Username (alphanumeric + . _ -, no spaces, 3–32 chars) ────────────────────
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.+\-]{3,32}$")

# ── Address (has digits AND letters AND spaces, 5+ chars) ─────────────────────
_ADDRESS_RE = re.compile(r"^(?=.*\d)(?=.*[a-zA-Z])(?=.*\s).{5,}$")


# ══════════════════════════════════════════════════════════════════════════════
# 3. VALUE CLASSIFIER  (order matters — most specific first)
# ══════════════════════════════════════════════════════════════════════════════

def classify_value(v: str) -> str:
    """
    Return a semantic field-type label for a single string value.

    Checks are ordered from most-specific to least-specific so that
    a hex hash isn't mislabelled as a username, etc.
    """
    v = v.strip()
    if not v:
        return "empty"

    # Email — has @, check first because it also matches username pattern
    if "@" in v:
        if _EMAIL_RE.match(v):
            return "email"
        return "email"      # still treat anything with @ as an email attempt

    # URL
    if _URL_RE.match(v):
        return "url"

    # SSN
    if _SSN_RE.match(v):
        return "ssn"

    # Hash (bcrypt / unix-crypt)
    if _HASH_CRYPT_RE.match(v):
        return "hash"

    # Hash (hex)
    if _HASH_HEX_RE.match(v) and len(v) in _HASH_LENGTHS:
        return "hash"

    # IPv4
    if _IPV4_RE.match(v):
        return "ip_address"

    # IPv6 (loose: contains colons and hex chars)
    if ":" in v and _IPV6_RE.match(v):
        return "ip_address"

    # Credit card (raw digits 13-19)
    if _CC_RAW_RE.match(v):
        n = len(v)
        if 13 <= n <= 19:
            return "credit_card"

    # Credit card (formatted)
    if _CC_FMT_RE.match(v) and 13 <= len(v.replace(" ", "").replace("-", "")) <= 19:
        return "credit_card"

    # Phone — strip formatting, check digit count
    stripped_phone = _PHONE_STRIP_RE.sub("", v)
    if _PHONE_CORE_RE.match(stripped_phone):
        return "phone"

    # Date
    if _DATE_RE.match(v):
        return "date"

    # US zip / international postal
    if _ZIP_US_RE.match(v):
        return "postal_code"
    if len(v) <= 8 and _POSTAL_INT_RE.match(v):
        return "postal_code"

    # Pure numeric → user_id / record id
    if _NUMERIC_ID_RE.match(v):
        return "user_id"

    # Name (capitalised word(s)) — check before username so "John Doe" wins
    if _NAME_RE.match(v):
        return "name"

    # Username (short, no spaces)
    if " " not in v and _USERNAME_RE.match(v):
        return "username"

    # Address (mixed letters + digits + spaces)
    if _ADDRESS_RE.match(v):
        return "address"

    # Default: treat as a password / opaque value
    return "password"


# ══════════════════════════════════════════════════════════════════════════════
# 4. COMBO LAYOUT TABLE
# ══════════════════════════════════════════════════════════════════════════════
# Maps field_count → ordered list of candidate label sequences.
# Real-world breach formats observed in the wild.

_COMBO_LAYOUTS: dict[int, list[list[str]]] = {
    2: [
        # Identity + auth
        ["email",      "password"],
        ["username",   "password"],
        ["email",      "hash"],
        ["username",   "hash"],
        ["email",      "username"],
        ["user_id",    "password"],
        ["user_id",    "email"],
        # Contact pairs
        ["phone",      "email"],
        ["email",      "phone"],
        ["name",       "email"],
        ["phone",      "name"],
        ["name",       "phone"],
        # Auth pairs
        ["url",        "password"],
        ["ip_address", "username"],
        ["username",   "email"],
        # Name split
        ["first_name", "last_name"],
        # Misc
        ["email",      "date"],
        ["username",   "date"],
    ],
    3: [
        # Classic combos
        ["email",      "password",  "hash"],
        ["username",   "email",     "password"],
        ["email",      "username",  "password"],
        ["username",   "password",  "hash"],
        ["user_id",    "email",     "password"],
        ["user_id",    "username",  "password"],
        # Name + contact
        ["first_name", "last_name", "email"],
        ["first_name", "last_name", "phone"],
        ["first_name", "last_name", "username"],
        ["name",       "email",     "password"],
        ["name",       "phone",     "email"],
        # With phone
        ["email",      "password",  "phone"],
        ["phone",      "email",     "password"],
        ["phone",      "username",  "password"],
        # With IP
        ["ip_address", "username",  "password"],
        ["ip_address", "email",     "password"],
        # With date
        ["email",      "password",  "date"],
        ["username",   "password",  "date"],
        # Location
        ["name",       "phone",     "address"],
    ],
    4: [
        ["first_name", "last_name", "email",      "password"],
        ["first_name", "last_name", "email",      "phone"],
        ["first_name", "last_name", "phone",      "email"],
        ["first_name", "last_name", "username",   "password"],
        ["username",   "email",     "password",   "hash"],
        ["user_id",    "username",  "email",      "password"],
        ["user_id",    "email",     "hash",       "phone"],
        ["email",      "username",  "password",   "phone"],
        ["email",      "password",  "hash",       "username"],
        ["name",       "email",     "phone",      "password"],
        ["ip_address", "username",  "password",   "email"],
        ["email",      "phone",     "name",       "password"],
        ["first_name", "last_name", "email",      "date"],
        ["first_name", "last_name", "phone",      "address"],
        ["email",      "password",  "phone",      "date"],
        ["username",   "email",     "phone",      "password"],
    ],
    5: [
        ["first_name", "last_name", "email",    "username",  "password"],
        ["first_name", "last_name", "email",    "phone",     "password"],
        ["first_name", "last_name", "email",    "password",  "hash"],
        ["first_name", "last_name", "phone",    "email",     "password"],
        ["user_id",    "username",  "email",    "password",  "phone"],
        ["name",       "email",     "phone",    "username",  "password"],
        ["user_id",    "first_name","last_name","email",     "password"],
        ["email",      "password",  "hash",     "phone",     "username"],
        ["first_name", "last_name", "email",    "phone",     "date"],
        ["first_name", "last_name", "address",  "phone",     "email"],
    ],
    6: [
        ["first_name", "last_name", "email",    "phone",    "username",  "password"],
        ["first_name", "last_name", "email",    "phone",    "password",  "hash"],
        ["user_id",    "first_name","last_name","email",    "phone",     "password"],
        ["first_name", "last_name", "email",    "username", "password",  "date"],
        ["name",       "email",     "phone",    "address",  "username",  "password"],
        ["first_name", "last_name", "address",  "phone",    "email",     "password"],
        ["user_id",    "username",  "email",    "password", "phone",     "date"],
    ],
    7: [
        ["user_id",    "first_name","last_name","email",    "phone",    "username",  "password"],
        ["first_name", "last_name", "address",  "email",    "phone",    "username",  "password"],
        ["first_name", "last_name", "email",    "phone",    "password", "hash",      "date"],
        ["user_id",    "first_name","last_name","address",  "phone",    "email",     "password"],
    ],
    8: [
        ["user_id",    "first_name","last_name","email",    "phone",    "address",   "username", "password"],
        ["first_name", "last_name", "address",  "postal_code","phone", "email",     "username", "password"],
    ],
}

# Groups of interchangeable types used for scoring partial matches
_TYPE_GROUPS: dict[str, str] = {
    "hash":        "secret",
    "password":    "secret",
    "email":       "contact",
    "phone":       "contact",
    "username":    "identity",
    "name":        "identity",
    "first_name":  "identity",
    "last_name":   "identity",
    "user_id":     "identity",
    "ip_address":  "network",
    "url":         "network",
    "address":     "location",
    "postal_code": "location",
    "date":        "temporal",
    "ssn":         "sensitive",
    "credit_card": "sensitive",
}


# ══════════════════════════════════════════════════════════════════════════════
# 5. LAYOUT SCORING AND SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def _best_layout(sample_rows: list[list[str]]) -> list[str]:
    """
    Given sample split rows, pick the label sequence that best matches.

    Scoring:
      +2  if the guessed type exactly matches the candidate label
      +1  if they are in the same type group (e.g. hash ↔ password)
      +0  otherwise

    Falls back to generic col_0 … col_N if no candidate layout exists.
    """
    if not sample_rows:
        return []

    n          = len(sample_rows[0])
    candidates = _COMBO_LAYOUTS.get(n, [])

    best_labels = [f"col_{i}" for i in range(n)]
    best_score  = -1

    for labels in candidates:
        score = 0
        for row in sample_rows:
            for label, val in zip(labels, row):
                guessed = classify_value(val)
                if label == guessed:
                    score += 2
                elif _TYPE_GROUPS.get(label) == _TYPE_GROUPS.get(guessed):
                    score += 1
        if score > best_score:
            best_score  = score
            best_labels = labels

    return best_labels


def _detect_combo_separator(data_lines: list[str]) -> tuple[str | None, int]:
    """
    Test candidate separators against the sample.
    Returns (best_sep, most_common_field_count) or (None, 0).

    Tries  :  ;  |  \\t  ,  in that order, picks first that achieves
    ≥ COMBO_THRESHOLD consistency across the sample.
    """
    for sep in _COMBO_SEPS:
        counts = Counter(
            line.count(sep)
            for line in data_lines
            if sep in line
        )
        if not counts:
            continue

        most_common_occ = counts.most_common(1)[0][0]
        if most_common_occ == 0:
            continue

        field_count = most_common_occ + 1
        consistent  = sum(
            1 for line in data_lines
            if len(line.split(sep)) == field_count
        )

        if consistent / max(len(data_lines), 1) >= _COMBO_THRESHOLD:
            return sep, field_count

    return None, 0


# ── Constants ──────────────────────────────────────────────────────────────────
_COMBO_SEPS      = [":", ";", "|", "\t", ","]
_COMBO_MIN_LINES = 15
_COMBO_THRESHOLD = 0.30
_SAMPLE_SIZE     = 100


# ══════════════════════════════════════════════════════════════════════════════
# 6. EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

class SmartTXTExtractor(BaseExtractor):
    """
    Adaptive parser for text / log / combo dump files.

    Recognises and handles
    ----------------------
    • Comment headers and inline comments  (#  //  --  ;  rem)
    • Separator lines  (---  ===  ***)
    • Blank lines
    • Structured combo lists with ANY mix of:
        email, password, hash, phone, username, name, user_id,
        ip_address, url, date, address, postal_code, ssn, credit_card

    Yields
    ------
    source_type="combo"         — full-row record + one per-field record
    source_type="txt"           — plain unstructured text lines
    source_type="txt_meta"      — comment / separator lines (still searchable)
    source_type="combo_malformed" — rows with unexpected field count
    """

    source_type = "txt"

    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        try:
            with open(source, encoding=self.encoding, errors="replace") as fh:
                raw_lines = fh.readlines()
        except Exception as exc:
            yield LeakerRecord(
                content=f"[Read error] {exc}",
                source=source,
                source_type="txt_error",
            )
            return

        yield from self._process(source, raw_lines)

    # ------------------------------------------------------------------

    def _process(
        self,
        source: str,
        raw_lines: list[str],
    ) -> Generator[LeakerRecord, None, None]:

        # ── Pass 1: classify every line ───────────────────────────────────
        classified: list[tuple[int, str, str]] = []   # (line_num, kind, text)

        for line_num, raw in enumerate(raw_lines, start=1):
            text     = raw.rstrip("\n\r")
            stripped = text.strip()

            if not stripped:
                classified.append((line_num, "blank",     text))
            elif _COMMENT_RE.match(stripped):
                classified.append((line_num, "comment",   text))
            elif _SEPARATOR_RE.match(stripped):
                classified.append((line_num, "separator", text))
            else:
                classified.append((line_num, "data",      text))

        # ── Pass 2: detect separator and layout from data lines ───────────
        data_lines = [
            text.strip()
            for _, kind, text in classified
            if kind == "data"
        ]

        sep:    str | None = None
        layout: list[str]  = []

        if len(data_lines) >= _COMBO_MIN_LINES:
            sample = data_lines[:_SAMPLE_SIZE]
            sep, field_count = _detect_combo_separator(sample)

            if sep and field_count >= 2:
                sample_rows = [
                    line.split(sep)
                    for line in sample
                    if len(line.split(sep)) == field_count
                ][:20]
                layout = _best_layout(sample_rows)

        # ── Pass 3: yield records ─────────────────────────────────────────
        for line_num, kind, text in classified:
            stripped = text.strip()

            if kind == "blank":
                continue

            if kind in ("comment", "separator"):
                yield LeakerRecord(
                    content=stripped,
                    source=source,
                    source_type="txt_meta",
                    line_number=line_num,
                    extra={"line_kind": kind},
                )
                continue

            # DATA line ───────────────────────────────────────────────────
            if sep and layout:
                parts = stripped.split(sep)

                if len(parts) == len(layout):
                    # Full combo row
                    yield LeakerRecord(
                        content=stripped,
                        source=source,
                        source_type="combo",
                        line_number=line_num,
                        extra={
                            "combo_sep": repr(sep),
                            "layout":    layout,
                            "fields":    dict(zip(layout, [p.strip() for p in parts])),
                        },
                    )
                    # Per-field records — individually searchable with semantic labels
                    for label, value in zip(layout, parts):
                        value = value.strip()
                        if value:
                            yield LeakerRecord(
                                content=value,
                                source=source,
                                source_type="combo",
                                line_number=line_num,
                                column_name=label,
                                extra={"layout": layout},
                            )
                    continue

                # Irregular row — don't silently drop it
                yield LeakerRecord(
                    content=stripped,
                    source=source,
                    source_type="combo_malformed",
                    line_number=line_num,
                    extra={"expected_fields": len(layout), "got": len(parts)},
                )
                continue

            # Plain text (no combo format detected)
            yield LeakerRecord(
                content=stripped,
                source=source,
                source_type=self.source_type,
                line_number=line_num,
            )
