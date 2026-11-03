"""
Excel Extractor (.xlsx / .xls / .ods) — all sheets, row + column provenance.
"""
from __future__ import annotations

from typing import Generator

import pandas as pd

from .base import BaseExtractor, LeakerRecord


class ExcelExtractor(BaseExtractor):
    source_type = "excel"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        xl = pd.ExcelFile(source)
        for sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name, dtype=str, keep_default_na=False)
            for row_idx, row in df.iterrows():
                row_num = int(row_idx) + 2   # header on row 1
                for col, val in row.items():
                    if str(val).strip():
                        yield LeakerRecord(
                            content=str(val),
                            source=source,
                            source_type=self.source_type,
                            line_number=row_num,
                            column_name=str(col),
                            sheet_name=str(sheet_name),
                        )
