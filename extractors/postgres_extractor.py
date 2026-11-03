"""
PostgreSQL Extractor — connects via psycopg2, iterates all tables in the
public schema (or a specified schema list).
"""
from __future__ import annotations

from typing import Generator, List

from .base import BaseExtractor, LeakerRecord


class PostgresExtractor(BaseExtractor):
    source_type = "postgres"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schemas: List[str] | None = None,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.schemas = schemas or ["public"]

    def extract(self, source: str = "") -> Generator[LeakerRecord, None, None]:
        import psycopg
        from psycopg.rows import dict_row

        label = source or f"postgres://{self.host}/{self.database}"
        conn = psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
        )
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                schema_list = ", ".join(f"'{s}'" for s in self.schemas)
                cur.execute(
                    f"""
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_schema IN ({schema_list})
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_schema, table_name
                    """
                )
                tables = cur.fetchall()

            for tbl in tables:
                schema = tbl["table_schema"]
                table = tbl["table_name"]
                fqn = f"{schema}.{table}"
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f'SELECT * FROM "{schema}"."{table}"')  # noqa: S608
                    for row_num, row in enumerate(cur, start=1):
                        for col, val in row.items():
                            if val is not None and str(val).strip():
                                yield LeakerRecord(
                                    content=str(val),
                                    source=label,
                                    source_type=self.source_type,
                                    line_number=row_num,
                                    column_name=col,
                                    table_name=fqn,
                                )
        finally:
            conn.close()
