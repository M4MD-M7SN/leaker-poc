"""
CSV Extractor — indexes every cell with its row and column provenance.
Uses pandas for robust delimiter/encoding detection.
"""
from __future__ import annotations

import csv
from typing import Generator

import pandas as pd

from .base import BaseExtractor, LeakerRecord


class CSVExtractor(BaseExtractor):
    source_type = "csv"

    def __init__(self, delimiter: str | None = None, encoding: str = "utf-8-sig"):
        self.delimiter = delimiter
        self.encoding = encoding

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        try:
            df = pd.read_csv(
                source,
                sep=self.delimiter,          # None → pandas sniffs
                engine="python",
                encoding=self.encoding,
                dtype=str,
                keep_default_na=False,
            )
        except Exception as exc:
            # Fallback: plain stdlib csv
            yield from self._fallback(source, exc)
            return

        for row_idx, row in df.iterrows():
            row_num = int(row_idx) + 2      # +1 header, +1 for 1-based
            full_row = " | ".join(f"{col}: {val}" for col, val in row.items() if val)
            if not full_row.strip():
                continue

            # One record per row (full row as content)
            yield LeakerRecord(
                content=full_row,
                source=source,
                source_type=self.source_type,
                line_number=row_num,
                extra={"columns": list(df.columns), "row": row.to_dict()},
            )

            # Also yield per-cell so individual values are searchable
            for col, val in row.items():
                if val and str(val).strip():
                    yield LeakerRecord(
                        content=str(val),
                        source=source,
                        source_type=self.source_type,
                        line_number=row_num,
                        column_name=str(col),
                        extra={"row_data": row.to_dict()},
                    )

    def _fallback(self, source: str, original_error: Exception):
        try:
            with open(source, newline="", encoding=self.encoding, errors="replace") as f:
                reader = csv.DictReader(f)
                for row_idx, row in enumerate(reader, start=2):
                    for col, val in row.items():
                        if val and str(val).strip():
                            yield LeakerRecord(
                                content=str(val),
                                source=source,
                                source_type=self.source_type,
                                line_number=row_idx,
                                column_name=col,
                            )
        except Exception:
            raise original_error
