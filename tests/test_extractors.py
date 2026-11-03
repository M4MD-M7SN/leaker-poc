"""
Basic unit tests for extractors — no Elasticsearch required.
"""
import os
import json
import sqlite3
import tempfile
import pytest

from extractors.csv_extractor import CSVExtractor
from extractors.txt_extractor import TXTExtractor
from extractors.json_extractor import JSONExtractor
from extractors.xml_extractor import XMLExtractor
from extractors.sqlite_extractor import SQLiteExtractor
from extractors.sql_file_extractor import SQLFileExtractor


# ── CSV ───────────────────────────────────────────────────────────────────────

def test_csv_extractor_basic(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("name,email\nAlice,alice@gmail.com\nBob,bob@yahoo.com\n")
    records = list(CSVExtractor().extract(str(f)))
    contents = [r.content for r in records]
    assert any("alice@gmail.com" in c for c in contents)
    assert any("bob@yahoo.com" in c for c in contents)


def test_csv_extractor_provenance(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text("name,email\nAlice,alice@gmail.com\n")
    records = [r for r in CSVExtractor().extract(str(f))
               if r.content == "alice@gmail.com"]
    assert records, "Expected a record for the email cell"
    r = records[0]
    assert r.column_name == "email"
    assert r.line_number == 2
    assert r.source_type == "csv"


# ── TXT ───────────────────────────────────────────────────────────────────────

def test_txt_extractor(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line one\n\nline three\n")
    records = list(TXTExtractor().extract(str(f)))
    assert len(records) == 2
    assert records[0].line_number == 1
    assert records[1].line_number == 3


# ── JSON ──────────────────────────────────────────────────────────────────────

def test_json_extractor_array(tmp_path):
    f = tmp_path / "test.json"
    f.write_text(json.dumps([{"email": "alice@gmail.com"}, {"email": "bob@yahoo.com"}]))
    records = list(JSONExtractor().extract(str(f)))
    contents = [r.content for r in records]
    assert "alice@gmail.com" in contents
    assert "bob@yahoo.com" in contents


def test_jsonl_extractor(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"email":"alice@gmail.com"}\n{"email":"bob@yahoo.com"}\n')
    records = list(JSONExtractor().extract(str(f)))
    contents = [r.content for r in records]
    assert "alice@gmail.com" in contents


# ── XML ───────────────────────────────────────────────────────────────────────

def test_xml_extractor(tmp_path):
    f = tmp_path / "test.xml"
    f.write_text(
        "<users><user><email>alice@gmail.com</email></user></users>"
    )
    records = list(XMLExtractor().extract(str(f)))
    assert any("alice@gmail.com" in r.content for r in records)


# ── SQLite ────────────────────────────────────────────────────────────────────

def test_sqlite_extractor(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER, email TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'alice@gmail.com')")
    conn.execute("INSERT INTO users VALUES (2, 'bob@yahoo.com')")
    conn.commit()
    conn.close()

    records = list(SQLiteExtractor().extract(db_path))
    contents = [r.content for r in records]
    assert "alice@gmail.com" in contents
    assert any(r.table_name == "users" for r in records)


# ── SQL File ──────────────────────────────────────────────────────────────────

def test_sql_file_extractor(tmp_path):
    f = tmp_path / "dump.sql"
    f.write_text(
        "INSERT INTO users VALUES (1, 'alice@gmail.com', '555-1234');"
    )
    records = list(SQLFileExtractor().extract(str(f)))
    contents = [r.content for r in records]
    assert any("alice@gmail.com" in c for c in contents)
