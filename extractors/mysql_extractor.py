"""
MySQL / MariaDB Extractor.
"""
from __future__ import annotations

from typing import Generator

from .base import BaseExtractor, LeakerRecord


class MySQLExtractor(BaseExtractor):
    source_type = "mysql"

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def extract(self, source: str = "") -> Generator[LeakerRecord, None, None]:
        import pymysql
        import pymysql.cursors

        label = source or f"mysql://{self.host}/{self.database}"
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_type='BASE TABLE'",
                    (self.database,),
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
                                    source_type=self.source_type,
                                    line_number=row_num,
                                    column_name=col,
                                    table_name=table,
                                )
        finally:
            conn.close()
