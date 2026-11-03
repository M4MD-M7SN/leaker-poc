"""
loader.py — Pre-Elasticsearch Organizer / Dispatcher
=====================================================

ROLE IN THE PIPELINE
--------------------

  [Raw files]  →  [loader.py]  →  [extractors/]  →  Elasticsearch
  (any format)    (dispatch)       (parse/normalize)  (index/search)

This module is the smart router between raw input and the parser layer.
It inspects each file's extension, selects the correct extractor, and
yields a stream of structured LeakerRecord objects — ready for indexing.

SUPPORTED INPUTS
----------------
  Files     : CSV, TSV, PSV, TXT, LOG, PDF, JSON, JSONL, XML, XLSX, XLS,
              ODS, SQLite, SQL dumps, DOCX
  Archives  : ZIP, TAR, GZ, TGZ, BZ2, 7z  (auto-extracted, then processed)
  Fallback  : Unknown extensions → SmartTXT adaptive parser
  Dirs      : Recursively walks the directory tree

The TXT / LOG fallback uses SmartTXTExtractor which handles noisy dump
files with comment headers, separator lines, and auto-detected combo
patterns (email:password, user:hash, etc.).
"""
from __future__ import annotations

import os
import glob as _glob
from typing import Generator

from extractors.base import BaseExtractor, LeakerRecord
from extractors.csv_extractor import CSVExtractor
from extractors.pdf_extractor import PDFExtractor
from extractors.txt_extractor import TXTExtractor
from extractors.smart_txt_extractor import SmartTXTExtractor
from extractors.json_extractor import JSONExtractor
from extractors.xml_extractor import XMLExtractor
from extractors.excel_extractor import ExcelExtractor
from extractors.sqlite_extractor import SQLiteExtractor
from extractors.sql_file_extractor import SQLFileExtractor
from extractors.docx_extractor import DocxExtractor

# Archive extensions handled by the watcher / inline unpack
_ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".tgz", ".bz2",
    ".tar.gz", ".tar.bz2", ".tar.xz", ".7z",
}

# SmartTXTExtractor is the default for plain-text / log / combo dumps.
# It handles comment headers, separator lines, and auto-detects
# structured combo patterns (email:password, user:hash, …).
_SMART_TXT = SmartTXTExtractor()

EXTENSION_MAP: dict[str, BaseExtractor] = {
    # Delimited files
    ".csv":    CSVExtractor(),
    ".tsv":    CSVExtractor(delimiter="\t"),
    ".psv":    CSVExtractor(delimiter="|"),
    # Text / log / combo dumps — smart adaptive parser
    ".txt":    _SMART_TXT,
    ".log":    _SMART_TXT,
    # Documents
    ".pdf":    PDFExtractor(),
    ".docx":   DocxExtractor(),
    # Structured data
    ".json":   JSONExtractor(),
    ".jsonl":  JSONExtractor(),
    ".ndjson": JSONExtractor(),
    ".xml":    XMLExtractor(),
    # Spreadsheets
    ".xlsx":   ExcelExtractor(),
    ".xls":    ExcelExtractor(),
    ".ods":    ExcelExtractor(),
    # Databases
    ".db":     SQLiteExtractor(),
    ".sqlite": SQLiteExtractor(),
    ".sqlite3":SQLiteExtractor(),
    ".sql":    SQLFileExtractor(),
}


def get_extractor(path: str) -> BaseExtractor | None:
    """Return the extractor for a file path, or None if it's an archive."""
    ext = os.path.splitext(path)[1].lower()
    # Archives are handled by the watcher / extract_file inline unpack
    if ext in _ARCHIVE_EXTENSIONS or path.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return None
    return EXTENSION_MAP.get(ext)


def extract_path(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Smart entry point — accepts a file, directory, or glob pattern.
    Archives are unpacked inline; unknown extensions fall back to SmartTXT.
    """
    expanded = _glob.glob(path, recursive=True)
    if not expanded:
        expanded = [path]

    for item in expanded:
        if os.path.isdir(item):
            yield from extract_directory(item)
        elif os.path.isfile(item):
            yield from extract_file(item)


def extract_file(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Extract records from a single file.

    Archives are unpacked into a temp directory and each extracted file is
    processed recursively.  Unknown extensions use the SmartTXT adaptive
    parser as a safe fallback.
    """
    import tempfile

    ext = os.path.splitext(path)[1].lower()
    full_lower = path.lower()

    # ── Inline archive unpacking ───────────────────────────────────────────
    if ext in _ARCHIVE_EXTENSIONS or any(
        full_lower.endswith(s) for s in (".tar.gz", ".tar.bz2", ".tar.xz")
    ):
        yield from _extract_archive(path)
        return

    # ── Normal file dispatch ───────────────────────────────────────────────
    extractor = EXTENSION_MAP.get(ext)
    if extractor is None:
        # Unknown extension — try the smart adaptive text parser
        try:
            yield from _SMART_TXT.extract(path)
        except Exception:
            pass
        return
    yield from extractor.extract(path)


def _extract_archive(path: str) -> Generator[LeakerRecord, None, None]:
    """
    Unpack a ZIP / TAR / 7z archive into a temp directory and yield records
    from every extracted file.  Nested archives are handled recursively.
    """
    import tarfile
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory(prefix="leaker_unpack_") as tmpdir:
        extracted_files: list[str] = []

        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path, "r") as zf:
                    safe = [
                        n for n in zf.namelist()
                        if not os.path.isabs(n) and ".." not in n
                    ]
                    for name in safe:
                        zf.extract(name, tmpdir)
                    extracted_files = [
                        os.path.join(tmpdir, n) for n in safe
                        if not n.endswith("/")
                    ]

            elif tarfile.is_tarfile(path):
                with tarfile.open(path, "r:*") as tf:
                    members = [
                        m for m in tf.getmembers()
                        if m.isfile()
                        and not os.path.isabs(m.name)
                        and ".." not in m.name
                    ]
                    tf.extractall(tmpdir, members=members)
                    extracted_files = [os.path.join(tmpdir, m.name) for m in members]

            else:
                # Try 7-zip
                try:
                    import py7zr
                    with py7zr.SevenZipFile(path, mode="r") as sz:
                        sz.extractall(path=tmpdir)
                    extracted_files = [
                        os.path.join(root, f)
                        for root, _, files in os.walk(tmpdir)
                        for f in files
                    ]
                except ImportError:
                    pass   # py7zr not installed — skip silently

        except Exception:
            pass   # Corrupt archive — skip

        for fpath in extracted_files:
            if os.path.isfile(fpath):
                yield from extract_file(fpath)   # recurse (handles nested zips)


def extract_directory(directory: str) -> Generator[LeakerRecord, None, None]:
    """Recursively walk a directory and extract every supported file."""
    for root, _, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            yield from extract_file(fpath)
