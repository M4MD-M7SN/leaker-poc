"""
SQL File Extractor — parses .sql dump files and extracts INSERT values.
Falls back to line-by-line text extraction if parsing fails.
"""
from __future__ import annotations

import re
from typing import Generator

from .base import BaseExtractor, LeakerRecord

# Matches: INSERT INTO `table` VALUES (...), (...);
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+[`'\"]?(\w+)[`'\"]?\s+(?:\([^)]+\)\s+)?VALUES\s*(.*?);",
    re.IGNORECASE | re.DOTALL,
)
# Split tuple groups
_VALUES_RE = re.compile(r"\(([^)]+)\)")


class SQLFileExtractor(BaseExtractor):
    source_type = "sql_file"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        with open(source, encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        found_insert = False
        for match in _INSERT_RE.finditer(content):
            found_insert = True
            table_name = match.group(1)
            values_block = match.group(2)
            for row_num, row_match in enumerate(_VALUES_RE.finditer(values_block), 1):
                raw = row_match.group(1)
                cells = [c.strip().strip("'\"") for c in raw.split(",")]
                row_text = " | ".join(c for c in cells if c)
                yield LeakerRecord(
                    content=row_text,
                    source=source,
                    source_type=self.source_type,
                    line_number=row_num,
                    table_name=table_name,
                )
                for idx, cell in enumerate(cells):
                    if cell.strip():
                        yield LeakerRecord(
                            content=cell.strip(),
                            source=source,
                            source_type=self.source_type,
                            line_number=row_num,
                            column_name=f"col_{idx}",
                            table_name=table_name,
                        )

        # If no INSERT statements found, index line-by-line
        if not found_insert:
            for line_num, line in enumerate(content.splitlines(), start=1):
                if line.strip() and not line.strip().startswith("--"):
                    yield LeakerRecord(
                        content=line.strip(),
                        source=source,
                        source_type=self.source_type,
                        line_number=line_num,
                    )
