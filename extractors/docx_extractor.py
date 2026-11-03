"""
Word Document Extractor (.docx) — paragraphs and tables.
"""
from __future__ import annotations

from typing import Generator

from .base import BaseExtractor, LeakerRecord


class DocxExtractor(BaseExtractor):
    source_type = "docx"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        from docx import Document

        doc = Document(source)
        for para_num, para in enumerate(doc.paragraphs, start=1):
            text = para.text.strip()
            if text:
                yield LeakerRecord(
                    content=text,
                    source=source,
                    source_type=self.source_type,
                    line_number=para_num,
                )

        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    text = cell.text.strip()
                    if text:
                        yield LeakerRecord(
                            content=text,
                            source=source,
                            source_type="docx_table",
                            extra={
                                "table_index": table_idx,
                                "row": row_idx,
                                "col": col_idx,
                            },
                        )
