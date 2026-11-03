"""
SQLite Extractor — iterates every table, every row.
"""
from __future__ import annotations

import sqlite3
from typing import Generator

from .base import BaseExtractor, LeakerRecord


class SQLiteExtractor(BaseExtractor):
    source_type = "sqlite"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        conn = sqlite3.connect(source)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            for table in tables:
                cursor.execute(f'SELECT * FROM "{table}"')  # noqa: S608
                columns = [desc[0] for desc in cursor.description]
                for row_num, row in enumerate(cursor, start=1):
                    for col, val in zip(columns, row):
                        if val is not None and str(val).strip():
                            yield LeakerRecord(
                                content=str(val),
                                source=source,
                                source_type=self.source_type,
                                line_number=row_num,
                                column_name=col,
                                table_name=table,
                            )
        finally:
            conn.close()
