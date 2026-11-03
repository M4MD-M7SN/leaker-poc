"""
functions.py — every function Leaker needs, organised into sections:

  1. Config
  2. Data model  (LeakerRecord)
  3. File extractors
       csv / tsv / psv
       txt / log
       pdf
       json / jsonl
       xml
       excel / ods
       sqlite
       sql dump files
       docx
  4. Database extractors
       postgresql
       mysql / mariadb
       mongodb
       redis
  5. Auto-loader  (dispatch by file extension or directory walk)
  6. Elasticsearch  (client, index creation, bulk index)
  7. Search         (full-text, exact, aggregations)
  8. Display        (rich tables, plain-text fallback)
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Standard-library imports
# ─────────────────────────────────────────────────────────────────────────────
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any, Generator, Iterable, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Third-party imports (all optional — only the ones you actually install)
# ─────────────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from tqdm import tqdm

load_dotenv()
console = Console()


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ES_HOST        = os.getenv("ES_HOST",         "http://localhost:9200")
ES_USERNAME    = os.getenv("ES_USERNAME",     "elastic")
ES_PASSWORD    = os.getenv("ES_PASSWORD",     "changeme")
ES_INDEX       = os.getenv("ES_INDEX_PREFIX", "leaker") + "_data"
ES_BATCH_SIZE  = int(os.getenv("ES_BATCH_SIZE", "500"))

PG_HOST        = os.getenv("PG_HOST",     "localhost")
PG_PORT        = int(os.getenv("PG_PORT", "5432"))
PG_USER        = os.getenv("PG_USER",     "postgres")
PG_PASSWORD    = os.getenv("PG_PASSWORD", "")
PG_DATABASE    = os.getenv("PG_DATABASE", "")

MYSQL_HOST     = os.getenv("MYSQL_HOST",     "localhost")
MYSQL_PORT     = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER     = os.getenv("MYSQL_USER",     "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")

MONGO_URI      = os.getenv("MONGO_URI",      "mongodb://localhost:27017")
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "")

REDIS_HOST     = os.getenv("REDIS_HOST",     "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")


# ══════════════════════════════════════════════════════════════════════════════
# 2. DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LeakerRecord:
    """
    One unit of indexed data — a single cell value, line, or document chunk.

    Every record carries its content AND exactly where it came from so that
    search results can show the full provenance chain.
    """
    content:     str                          # The raw text value
    source:      str                          # File path or DB connection label
    source_type: str                          # csv | pdf | sqlite | postgres | …

    line_number: Optional[int]  = None        # Row / line number (1-based)
    column_name: Optional[str]  = None        # Column or field name
    table_name:  Optional[str]  = None        # DB table / collection / sheet
    page_number: Optional[int]  = None        # PDF page number
    extra:       dict           = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        """Deterministic SHA-256 ID — re-indexing the same data is idempotent."""
        raw = f"{self.source}|{self.source_type}|{self.line_number}|{self.content[:64]}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["doc_id"] = self.doc_id
        return d


# ══════════════════════════════════════════════════════════════════════════════
# 3. FILE EXTRACTORS
# ══════════════════════════════════════════════════════════════════════════════

# ── 3a. CSV / TSV / PSV ───────────────────────────────────────────────────────

def extract_csv(
    path: str,
    delimiter: Optional[str] = None,
    encoding: str = "utf-8-sig",
) -> Generator[LeakerRecord, None, None]:
    """
    Extract every cell from a delimited file.

    Yields two kinds of records per row:
      - A full-row record (all columns joined) for row-level search
      - One per-cell record for precise column-level search
    """
    import pandas as pd

    try:
        df = pd.read_csv(
            path,
            sep=delimiter,        # None → pandas sniffs the delimiter
            engine="python",
            encoding=encoding,
            dtype=str,
            keep_default_na=False,
        )
    except Exception:
        # Fallback to stdlib csv so we never completely fail
        yield from _csv_fallback(path, encoding)
        return

    for row_idx, row in df.iterrows():
        row_num   = int(row_idx) + 2          # row 1 = header, so data starts at 2
        full_row  = " | ".join(
            f"{col}: {val}" for col, val in row.items() if str(val).strip()
        )
        if not full_row.strip():
            continue

        # Full-row record
        yield LeakerRecord(
            content=full_row,
            source=path,
            source_type="csv",
            line_number=row_num,
            extra={"columns": list(df.columns), "row": row.to_dict()},
        )

        # Per-cell records
        for col, val in row.items():
            val = str(val).strip()
            if val:
                yield LeakerRecord(
                    content=val,
                    source=path,
                    source_type="csv",
                    line_number=row_num,
                    column_name=str(col),
                    extra={"row_data": row.to_dict()},
                )


def _csv_fallback(
    path: str,
    encoding: str,
) -> Generator[LeakerRecord, None, None]:
    """stdlib csv fallback when pandas fails."""
    with open(path, newline="", encoding=encoding, errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=2):
            for col, val in row.items():
                if val and str(val).strip():
                    yield LeakerRecord(
                        content=str(val),
                        source=path,
                        source_type="csv",
                        line_number=row_num,
                        column_name=col,
                    )


# ── 3b. TXT / LOG ────────────────────────────────────────────────────────────

def extract_txt(
    path: str,
    encoding: str = "utf-8",
) -> Generator[LeakerRecord, None, None]:
    """One record per non-empty line."""
    with open(path, encoding=encoding, errors="replace") as fh:
        for line_num, line in enumerate(fh, start=1):
            stripped = line.rstrip("\n\r")
            if stripped.strip():
                yield LeakerRecord(
                    content=stripped,
                    source=path,
                    source_type="txt",
                    line_number=line_num,
                )


# ── 3c. PDF ───────────────────────────────────────────────────────────────────

def extract_pdf(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Extract PDF text page-by-page using pdfplumber (table-aware).
    Falls back to pypdf if pdfplumber is not installed.
    Also extracts table cell values individually.
    """
    try:
        import pdfplumber
        yield from _pdf_pdfplumber(path)
    except ImportError:
        yield from _pdf_pypdf(path)


def _pdf_pdfplumber(path: str) -> Generator[LeakerRecord, None, None]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):

            # Plain text lines
            text = page.extract_text() or ""
            for line_num, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    yield LeakerRecord(
                        content=line.strip(),
                        source=path,
                        source_type="pdf",
                        line_number=line_num,
                        page_number=page_num,
                    )

            # Table cells
            for tbl_idx, table in enumerate(page.extract_tables() or []):
                for row_idx, row in enumerate(table):
                    for col_idx, cell in enumerate(row or []):
                        if cell and str(cell).strip():
                            yield LeakerRecord(
                                content=str(cell).strip(),
                                source=path,
                                source_type="pdf_table",
                                page_number=page_num,
                                extra={"table": tbl_idx, "row": row_idx, "col": col_idx},
                            )


def _pdf_pypdf(path: str) -> Generator[LeakerRecord, None, None]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for line_num, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                yield LeakerRecord(
                    content=line.strip(),
                    source=path,
                    source_type="pdf",
                    line_number=line_num,
                    page_number=page_num,
                )


# ── 3d. JSON / JSONL ─────────────────────────────────────────────────────────

def extract_json(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Flatten nested JSON into leaf values, yielding one record per value.
    Column names are dotpath strings: e.g. "user.address.city"
    Supports both JSON arrays/objects and newline-delimited JSONL.
    """
    is_jsonl = path.endswith((".jsonl", ".ndjson"))

    with open(path, encoding="utf-8", errors="replace") as fh:
        if is_jsonl:
            yield from _jsonl_lines(fh, path)
        else:
            yield from _json_object(fh, path)


def _json_object(fh, path: str) -> Generator[LeakerRecord, None, None]:
    try:
        data = json.load(fh)
    except json.JSONDecodeError as exc:
        yield LeakerRecord(content=f"[JSON parse error] {exc}", source=path,
                           source_type="json", line_number=exc.lineno)
        return

    items = data if isinstance(data, list) else [data]
    for idx, item in enumerate(items, start=1):
        yield from _flatten_value(item, path, "json", idx)


def _jsonl_lines(fh, path: str) -> Generator[LeakerRecord, None, None]:
    for line_num, line in enumerate(fh, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            yield from _flatten_value(obj, path, "jsonl", line_num)
        except json.JSONDecodeError:
            yield LeakerRecord(content=line, source=path,
                               source_type="jsonl", line_number=line_num)


def _flatten_value(
    obj: Any,
    source: str,
    source_type: str,
    line_number: int,
    prefix: str = "",
) -> Generator[LeakerRecord, None, None]:
    """Recursively flatten dicts and lists to leaf string values."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{prefix}.{key}" if prefix else key
            yield from _flatten_value(val, source, source_type, line_number, child)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            yield from _flatten_value(item, source, source_type, line_number,
                                      f"{prefix}[{idx}]")
    else:
        val_str = str(obj).strip()
        if val_str:
            yield LeakerRecord(
                content=val_str,
                source=source,
                source_type=source_type,
                line_number=line_number,
                column_name=prefix or None,
            )


# ── 3e. XML ───────────────────────────────────────────────────────────────────

def extract_xml(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Walk the XML element tree and yield every text node and attribute value.
    Column names are XPath-style strings: e.g. "users/user/email"
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as exc:
        yield LeakerRecord(content=f"[XML error] {exc}", source=path,
                           source_type="xml")
        return

    yield from _walk_xml(root, path, root.tag)


def _walk_xml(
    element,
    source: str,
    path: str,
) -> Generator[LeakerRecord, None, None]:
    text = (element.text or "").strip()
    if text:
        yield LeakerRecord(content=text, source=source,
                           source_type="xml", column_name=path)

    for attr_name, attr_val in element.attrib.items():
        if attr_val.strip():
            yield LeakerRecord(content=attr_val, source=source,
                               source_type="xml", column_name=f"{path}@{attr_name}")

    for child in element:
        yield from _walk_xml(child, source, f"{path}/{child.tag}")


# ── 3f. Excel / ODS ──────────────────────────────────────────────────────────

def extract_excel(path: str) -> Generator[LeakerRecord, None, None]:
    """All sheets, every cell, with sheet name + row + column provenance."""
    import pandas as pd

    xl = pd.ExcelFile(path)
    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name, dtype=str, keep_default_na=False)
        for row_idx, row in df.iterrows():
            row_num = int(row_idx) + 2
            for col, val in row.items():
                if str(val).strip():
                    yield LeakerRecord(
                        content=str(val),
                        source=path,
                        source_type="excel",
                        line_number=row_num,
                        column_name=str(col),
                        table_name=str(sheet_name),
                    )


# ── 3g. SQLite ────────────────────────────────────────────────────────────────

def extract_sqlite(path: str) -> Generator[LeakerRecord, None, None]:
    """Every table, every row, every cell — with table + column provenance."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]

        for table in tables:
            cur.execute(f'SELECT * FROM "{table}"')  # noqa: S608
            columns = [d[0] for d in cur.description]
            for row_num, row in enumerate(cur, start=1):
                for col, val in zip(columns, row):
                    if val is not None and str(val).strip():
                        yield LeakerRecord(
                            content=str(val),
                            source=path,
                            source_type="sqlite",
                            line_number=row_num,
                            column_name=col,
                            table_name=table,
                        )
    finally:
        conn.close()


# ── 3h. SQL dump files ────────────────────────────────────────────────────────

# Matches:  INSERT INTO `tablename` VALUES (...), (...);
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+[`'\"]?(\w+)[`'\"]?\s+(?:\([^)]+\)\s+)?VALUES\s*(.*?);",
    re.IGNORECASE | re.DOTALL,
)
_TUPLE_RE = re.compile(r"\(([^)]+)\)")


def extract_sql_file(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Parse INSERT statements in a SQL dump file.
    Falls back to line-by-line text if no INSERT statements are found.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    found_inserts = False
    for match in _INSERT_RE.finditer(content):
        found_inserts = True
        table_name   = match.group(1)
        values_block = match.group(2)

        for row_num, tuple_match in enumerate(_TUPLE_RE.finditer(values_block), start=1):
            raw   = tuple_match.group(1)
            cells = [c.strip().strip("'\"") for c in raw.split(",")]
            row_text = " | ".join(c for c in cells if c.strip())

            # Full-row record
            yield LeakerRecord(
                content=row_text,
                source=path,
                source_type="sql_file",
                line_number=row_num,
                table_name=table_name,
            )
            # Per-cell records
            for col_idx, cell in enumerate(cells):
                if cell.strip():
                    yield LeakerRecord(
                        content=cell.strip(),
                        source=path,
                        source_type="sql_file",
                        line_number=row_num,
                        column_name=f"col_{col_idx}",
                        table_name=table_name,
                    )

    # No INSERT statements — index line by line
    if not found_inserts:
        for line_num, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if line and not line.startswith("--"):
                yield LeakerRecord(
                    content=line,
                    source=path,
                    source_type="sql_file",
                    line_number=line_num,
                )


# ── 3i. DOCX ─────────────────────────────────────────────────────────────────

def extract_docx(path: str) -> Generator[LeakerRecord, None, None]:
    """Paragraphs and table cells from a Word .docx file."""
    from docx import Document

    doc = Document(path)
    for para_num, para in enumerate(doc.paragraphs, start=1):
        if para.text.strip():
            yield LeakerRecord(
                content=para.text.strip(),
                source=path,
                source_type="docx",
                line_number=para_num,
            )

    for tbl_idx, table in enumerate(doc.tables):
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                if cell.text.strip():
                    yield LeakerRecord(
                        content=cell.text.strip(),
                        source=path,
                        source_type="docx_table",
                        extra={"table": tbl_idx, "row": row_idx, "col": col_idx},
                    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. DATABASE EXTRACTORS
# ══════════════════════════════════════════════════════════════════════════════

# ── 4a. PostgreSQL ────────────────────────────────────────────────────────────

def extract_postgres(
    host: str     = PG_HOST,
    port: int     = PG_PORT,
    user: str     = PG_USER,
    password: str = PG_PASSWORD,
    database: str = PG_DATABASE,
    schemas: Optional[List[str]] = None,
) -> Generator[LeakerRecord, None, None]:
    """
    Connect to a PostgreSQL database and yield every cell from every table
    in the specified schemas (default: public).
    """
    import psycopg
    from psycopg.rows import dict_row

    schemas = schemas or ["public"]
    label   = f"postgres://{host}:{port}/{database}"
    conn    = psycopg.connect(host=host, port=port, user=user,
                              password=password, dbname=database)
    try:
        schema_list = ", ".join(f"'{s}'" for s in schemas)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT table_schema, table_name "
                f"FROM information_schema.tables "
                f"WHERE table_schema IN ({schema_list}) AND table_type='BASE TABLE' "
                f"ORDER BY table_schema, table_name"
            )
            tables = cur.fetchall()

        for tbl in tables:
            fqn = f"{tbl['table_schema']}.{tbl['table_name']}"
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f'SELECT * FROM "{tbl["table_schema"]}"."{tbl["table_name"]}"')  # noqa: S608
                for row_num, row in enumerate(cur, start=1):
                    for col, val in row.items():
                        if val is not None and str(val).strip():
                            yield LeakerRecord(
                                content=str(val),
                                source=label,
                                source_type="postgres",
                                line_number=row_num,
                                column_name=col,
                                table_name=fqn,
                            )
    finally:
        conn.close()


# ── 4b. MySQL / MariaDB ───────────────────────────────────────────────────────

def extract_mysql(
    host: str     = MYSQL_HOST,
    port: int     = MYSQL_PORT,
    user: str     = MYSQL_USER,
    password: str = MYSQL_PASSWORD,
    database: str = MYSQL_DATABASE,
) -> Generator[LeakerRecord, None, None]:
    """Connect to MySQL / MariaDB and yield every cell from every table."""
    import pymysql
    import pymysql.cursors

    label = f"mysql://{host}:{port}/{database}"
    conn  = pymysql.connect(host=host, port=port, user=user, password=password,
                             database=database,
                             cursorclass=pymysql.cursors.DictCursor,
                             charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE'",
                (database,),
            )
            tables = [r["table_name"] for r in cur.fetchall()]

        for table in tables:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM `{table}`")  # noqa: S608
                for row_num, row in enumerate(cur, start=1):
                    for col, val in row.items():
                        if val is not None and str(val).strip():
                            yield LeakerRecord(
                                content=str(val),
                                source=label,
                                source_type="mysql",
                                line_number=row_num,
                                column_name=col,
                                table_name=table,
                            )
    finally:
        conn.close()


# ── 4c. MongoDB ───────────────────────────────────────────────────────────────

def extract_mongo(
    uri: str      = MONGO_URI,
    database: str = MONGO_DATABASE,
) -> Generator[LeakerRecord, None, None]:
    """
    Connect to MongoDB and yield every field from every document in every
    collection. Nested objects are flattened to dotpath keys.
    """
    from pymongo import MongoClient

    label  = uri
    client = MongoClient(uri)
    db     = client[database]
    try:
        for coll_name in db.list_collection_names():
            collection = db[coll_name]
            for row_num, doc in enumerate(collection.find(), start=1):
                doc.pop("_id", None)
                yield from _flatten_value(doc, label, "mongodb", row_num)
    finally:
        client.close()


# ── 4d. Redis ─────────────────────────────────────────────────────────────────

def extract_redis(
    host: str     = REDIS_HOST,
    port: int     = REDIS_PORT,
    password: str = REDIS_PASSWORD,
    db: int       = 0,
) -> Generator[LeakerRecord, None, None]:
    """
    Dump all keys from Redis.
    Handles: string, hash, list, set, zset key types.
    """
    import redis as redis_lib

    label  = f"redis://{host}:{port}/{db}"
    client = redis_lib.Redis(
        host=host, port=port,
        password=password or None,
        db=db,
        decode_responses=True,
    )
    for key in client.scan_iter("*"):
        key_type = client.type(key)

        if key_type == "string":
            val = client.get(key) or ""
            if val.strip():
                yield LeakerRecord(content=val, source=label,
                                   source_type="redis", column_name=key)

        elif key_type == "hash":
            for field_name, val in client.hgetall(key).items():
                if val.strip():
                    yield LeakerRecord(content=val, source=label,
                                       source_type="redis",
                                       column_name=f"{key}:{field_name}")

        elif key_type == "list":
            for idx, val in enumerate(client.lrange(key, 0, -1)):
                if val.strip():
                    yield LeakerRecord(content=val, source=label,
                                       source_type="redis",
                                       column_name=f"{key}[{idx}]")

        elif key_type in ("set", "zset"):
            members = client.smembers(key) if key_type == "set" \
                      else client.zrange(key, 0, -1)
            for val in members:
                if val.strip():
                    yield LeakerRecord(content=val, source=label,
                                       source_type="redis", column_name=key)


# ══════════════════════════════════════════════════════════════════════════════
# 5. AUTO-LOADER  (dispatch by extension / directory walk)
# ══════════════════════════════════════════════════════════════════════════════

# Map file extension → extractor function
EXTENSION_MAP: dict[str, Any] = {
    ".csv":    extract_csv,
    ".tsv":    lambda p: extract_csv(p, delimiter="\t"),
    ".psv":    lambda p: extract_csv(p, delimiter="|"),
    ".txt":    extract_txt,
    ".log":    extract_txt,
    ".pdf":    extract_pdf,
    ".json":   extract_json,
    ".jsonl":  extract_json,
    ".ndjson": extract_json,
    ".xml":    extract_xml,
    ".xlsx":   extract_excel,
    ".xls":    extract_excel,
    ".ods":    extract_excel,
    ".db":     extract_sqlite,
    ".sqlite": extract_sqlite,
    ".sqlite3":extract_sqlite,
    ".sql":    extract_sql_file,
    ".docx":   extract_docx,
}


def extract_file(path: str) -> Generator[LeakerRecord, None, None]:
    """Detect format by extension and delegate to the right extractor."""
    ext = os.path.splitext(path)[1].lower()
    fn  = EXTENSION_MAP.get(ext)
    if fn is None:
        # Unknown extension — try plain text
        try:
            yield from extract_txt(path)
        except Exception:
            pass
        return
    yield from fn(path)


def extract_directory(directory: str) -> Generator[LeakerRecord, None, None]:
    """Recursively walk a directory and extract every supported file."""
    for root, _, files in os.walk(directory):
        for fname in files:
            yield from extract_file(os.path.join(root, fname))


def extract_path(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Smart entry point: accepts a file, directory, or glob pattern.
    Returns a generator of LeakerRecord objects regardless of input type.
    """
    import glob as _glob

    expanded = _glob.glob(path, recursive=True)
    targets  = expanded if expanded else [path]

    for target in targets:
        if os.path.isdir(target):
            yield from extract_directory(target)
        elif os.path.isfile(target):
            yield from extract_file(target)


# ══════════════════════════════════════════════════════════════════════════════
# 6. ELASTICSEARCH — CLIENT, INDEX SETUP, BULK INDEXER
# ══════════════════════════════════════════════════════════════════════════════

# Index mapping — defines field types and the custom email/URL analyser
INDEX_MAPPING = {
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
        "analysis": {
            "filter": {
                # split "alice@gmail.com" into alice / gmail / com (and keep the
                # whole address) so partial searches like "gmail" match too.
                "email_parts": {
                    "type":                   "word_delimiter",
                    "preserve_original":      True,
                    "split_on_numerics":      False,
                    "split_on_case_change":   False,
                    "catenate_words":         False,
                    "catenate_numbers":       False,
                    "stem_english_possessive": False,
                },
            },
            "analyzer": {
                # uax_url_email keeps the full address as one token; email_parts
                # then also emits the pieces (user / domain / tld).
                "email_analyzer": {
                    "type":      "custom",
                    "tokenizer": "uax_url_email",
                    "filter":    ["lowercase", "email_parts"],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "content":     {"type": "text", "analyzer": "email_analyzer",
                            "fields": {"keyword": {"type": "keyword",
                                                   "ignore_above": 512}}},
            "source":      {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "line_number": {"type": "integer"},
            "column_name": {"type": "keyword"},
            "table_name":  {"type": "keyword"},
            "page_number": {"type": "integer"},
            "doc_id":      {"type": "keyword"},
            "extra":       {"type": "object", "enabled": False},
        }
    },
}


def get_es_client(
    host: str     = ES_HOST,
    username: str = ES_USERNAME,
    password: str = ES_PASSWORD,
) -> Elasticsearch:
    """Return a configured Elasticsearch client."""
    return Elasticsearch(
        host,
        basic_auth=(username, password),
        verify_certs=False,
        request_timeout=30,
    )


def ensure_index(es: Elasticsearch, index: str = ES_INDEX) -> None:
    """Create the index with the Leaker mapping if it does not already exist."""
    if not es.indices.exists(index=index):
        es.indices.create(index=index, body=INDEX_MAPPING)
        console.print(f"[green]Created index:[/green] {index}")


def index_records(
    es: Elasticsearch,
    records: Iterable[LeakerRecord],
    index: str = ES_INDEX,
    show_progress: bool = True,
) -> tuple[int, int]:
    """
    Bulk-stream LeakerRecord objects into Elasticsearch.

    Uses streaming_bulk so memory stays flat no matter how large the dataset.
    Returns (success_count, error_count).
    """
    ensure_index(es, index)

    def _actions():
        for rec in records:
            doc = rec.to_dict()
            yield {"_index": index, "_id": doc["doc_id"], "_source": doc}

    gen = _actions()
    if show_progress:
        gen = tqdm(gen, desc="Indexing", unit=" docs", file=sys.stdout)

    ok = err = 0
    for success, info in streaming_bulk(es, gen, chunk_size=ES_BATCH_SIZE,
                                        raise_on_error=False):
        if success:
            ok  += 1
        else:
            err += 1
            console.print(f"[red][!] Index error:[/red] {info}", highlight=False)

    return ok, err


# ══════════════════════════════════════════════════════════════════════════════
# 7. SEARCH
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SearchResult:
    content:     str
    source:      str
    source_type: str
    line_number: Optional[int]
    column_name: Optional[str]
    table_name:  Optional[str]
    page_number: Optional[int]
    score:       float

    def location_str(self) -> str:
        parts = []
        if self.table_name:  parts.append(f"table={self.table_name}")
        if self.page_number: parts.append(f"page={self.page_number}")
        if self.line_number: parts.append(f"line={self.line_number}")
        if self.column_name: parts.append(f"col={self.column_name}")
        return ", ".join(parts) or "—"

    def plain(self) -> str:
        return (
            f"  [{self.source_type}] {self.source}\n"
            f"  Location : {self.location_str()}\n"
            f"  Content  : {self.content}\n"
            f"  Score    : {self.score:.4f}"
        )


def search(
    es: Elasticsearch,
    query: str,
    *,
    exact: bool                 = False,
    source_types: Optional[List[str]] = None,
    sources:      Optional[List[str]] = None,
    size: int  = 20,
    page: int  = 1,
    index: str = ES_INDEX,
) -> List[SearchResult]:
    """
    Search all indexed data.

    Parameters
    ----------
    query        : The search string — email, name, phone, hash, keyword, …
    exact        : True → term query on keyword field (case-sensitive exact match)
                   False → multi_match fuzzy full-text (default)
    source_types : Restrict results to these source types  e.g. ["csv","sqlite"]
    sources      : Restrict results to these source paths / labels
    size         : Results per page
    page         : Page number (1-based)
    index        : Elasticsearch index name
    """
    # Build the must clause
    if exact:
        must = [{"term": {"content.keyword": query}}]
    else:
        must = [{
            "multi_match": {
                "query":     query,
                "fields":    ["content^3", "column_name", "table_name", "source"],
                "type":      "best_fields",
                "fuzziness": "AUTO",
            }
        }]

    # Optional filters
    filters = []
    if source_types:
        filters.append({"terms": {"source_type": source_types}})
    if sources:
        filters.append({"terms": {"source": sources}})

    base_query = {"bool": {"must": must, **({"filter": filters} if filters else {})}}
    # Rank real breach dumps above the tiny demo files in examples/.
    es_query = {
        "boosting": {
            "positive":       base_query,
            "negative":       {"prefix": {"source": "examples/"}},
            "negative_boost": 0.15,
        }
    }

    resp = es.search(
        index=index,
        query=es_query,
        size=size,
        from_=(page - 1) * size,
        # collapse identical rows (same record repeated at different line numbers)
        collapse={"field": "content.keyword"},
        highlight={
            "fields":    {"content": {"number_of_fragments": 0}},
            # sentinels (not ANSI) so the renderer can style matches cleanly
            "pre_tags":  [""],
            "post_tags": [""],
        },
    )

    results = []
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        hl  = hit.get("highlight", {}).get("content", [])
        results.append(SearchResult(
            content     = hl[0] if hl else src.get("content", ""),
            source      = src.get("source", ""),
            source_type = src.get("source_type", ""),
            line_number = src.get("line_number"),
            column_name = src.get("column_name"),
            table_name  = src.get("table_name"),
            page_number = src.get("page_number"),
            score       = hit["_score"],
        ))
    return results


def count_hits(es: Elasticsearch, query: str, index: str = ES_INDEX) -> int:
    """Return total document count matching query."""
    resp = es.count(index=index, query={"match": {"content": query}})
    return resp["count"]


def list_sources(es: Elasticsearch, index: str = ES_INDEX) -> List[dict]:
    """
    Return all indexed sources with their document counts and type breakdown.
    Uses Elasticsearch aggregations — no full scan needed.
    """
    resp = es.search(
        index=index,
        size=0,
        aggs={
            "by_source": {
                "terms": {"field": "source", "size": 1000},
                "aggs":  {"by_type": {"terms": {"field": "source_type", "size": 20}}},
            }
        },
    )
    sources = []
    for bucket in resp["aggregations"]["by_source"]["buckets"]:
        types = [b["key"] for b in bucket["by_type"]["buckets"]]
        sources.append({
            "source": bucket["key"],
            "count":  bucket["doc_count"],
            "types":  types,
        })
    return sources


def delete_index(es: Elasticsearch, index: str = ES_INDEX) -> None:
    """Delete the Elasticsearch index (wipes all indexed data)."""
    es.indices.delete(index=index, ignore_unavailable=True)


# ══════════════════════════════════════════════════════════════════════════════
# 8. DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

HL_OPEN, HL_CLOSE = "\x01", "\x02"


def _strip_hl(s: str) -> str:
    """Remove highlight sentinels (for plain/raw output)."""
    return s.replace(HL_OPEN, "").replace(HL_CLOSE, "")


def _elide(s: str, n: int = 160) -> str:
    for esc in ("\\n", "\\r", "\\t"):
        s = s.replace(esc, " ")
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def _hl_text(s: str, base_style: str = "") -> Text:
    """Build a rich Text from a string with \\x01..\\x02 highlight sentinels,
    styling the matched spans so they pop without fighting the layout."""
    t = Text()
    i = 0
    while i < len(s):
        o = s.find(HL_OPEN, i)
        if o == -1:
            t.append(s[i:], style=base_style)
            break
        t.append(s[i:o], style=base_style)
        c = s.find(HL_CLOSE, o + 1)
        if c == -1:
            t.append(s[o + 1:], style="bold black on yellow")
            break
        t.append(s[o + 1:c], style="bold black on yellow")
        i = c + 1
    return t


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _split_fields(content: str) -> List[str]:
    """Break a record into its individual fields. SQL/TSV rows are tab-joined;
    labelled CSV full-rows use ' | '."""
    if "\t" in content:
        parts = content.split("\t")
    elif " | " in content:
        parts = content.split(" | ")
    else:
        parts = [content]
    return [p for p in parts if p.strip()]


def _lead_value(fields: List[str]) -> Optional[str]:
    """The field to surface first: the matched email if any, else the first
    field carrying the match, else any email in the record."""
    matched = [f for f in fields if HL_OPEN in f]
    for pool in (matched, fields):
        for f in pool:
            if _EMAIL_RE.search(_strip_hl(f)):
                return f
    return matched[0] if matched else None


def _result_panel(r: "SearchResult", rank: int) -> Panel:
    """One hit as a clean card: the matched email surfaced up top, then the full
    record split into fields, with matches highlighted and short provenance."""
    src_name = os.path.basename(r.source.rstrip("/")) or r.source
    fields = _split_fields(r.content)

    body = Text()
    lead = _lead_value(fields)
    if lead is not None:
        body.append("✉  ", style="bold green")
        body.append_text(_hl_text(_elide(lead), base_style="bold"))
        body.append("\n")
        body.append("─" * 24 + "\n", style="grey37")

    if len(fields) <= 1:
        body.append_text(_hl_text(_elide(r.content)))
    else:
        width = len(str(len(fields)))
        for n, fval in enumerate(fields, 1):
            body.append(f"{n:>{width}}  ", style="dim")
            body.append_text(_hl_text(_elide(fval)))
            if n != len(fields):
                body.append("\n")

    loc = r.location_str()
    title = (f"[bold]#{rank}[/]  [dim]score[/] [green]{r.score:.1f}[/]   "
             f"[cyan]{src_name}[/]"
             + (f"  [dim]· {loc}[/]" if loc != "—" else "")
             + f"   [magenta]{r.source_type}[/]")
    return Panel(body, title=title, title_align="left",
                 border_style="grey37", box=box.ROUNDED, padding=(0, 1))


def display_results(
    results: List[SearchResult],
    query: str,
    total: int,
    page: int,
    raw: bool = False,
) -> None:
    """
    Print search results to the terminal.

    raw=False  → rich table with colour and borders (default)
    raw=True   → plain text, one result per block (good for piping / grep)
    """
    if not results:
        console.print(f"[yellow]No results found for:[/yellow] {query!r}")
        return

    console.print(
        f"\n  [bold green]{total:,}[/] matches for [bold yellow]{query}[/]"
        f"   [dim]· showing {len(results)} (page {page})[/]\n"
    )

    if raw:
        for r in results:
            print(_strip_hl(r.content))
            print(f"  [{r.source_type}] {r.source}  {r.location_str()}  "
                  f"score={r.score:.3f}")
            print()
        return

    start = (page - 1) * len(results)
    for i, r in enumerate(results, start + 1):
        console.print(_result_panel(r, i))

    console.print(
        f"\n  [dim]Tip: [/][cyan]:exact[/][dim] for exact match · [/]"
        f"[cyan]:type txt[/][dim] to filter source type · [/]"
        f"[cyan]:help[/][dim] for all commands[/]\n"
    )


def display_sources(sources: List[dict]) -> None:
    """Print indexed sources as a rich table."""
    if not sources:
        console.print("[yellow]No sources indexed yet.[/yellow]")
        return

    table = Table("Source", "Types", "Documents", box=box.ROUNDED)
    for s in sources:
        table.add_row(s["source"], ", ".join(s["types"]), f"{s['count']:,}")
    console.print(table)
