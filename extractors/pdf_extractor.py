"""
PDF Extractor — extracts text page-by-page using pdfplumber (table-aware)
with pypdf as fallback.
"""
from __future__ import annotations

from typing import Generator

from .base import BaseExtractor, LeakerRecord


class PDFExtractor(BaseExtractor):
    source_type = "pdf"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        try:
            import pdfplumber
            yield from self._extract_pdfplumber(source)
        except ImportError:
            yield from self._extract_pypdf(source)

    def _extract_pdfplumber(self, source: str):
        import pdfplumber

        with pdfplumber.open(source) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                for line_num, line in enumerate(text.splitlines(), start=1):
                    if line.strip():
                        yield LeakerRecord(
                            content=line.strip(),
                            source=source,
                            source_type=self.source_type,
                            line_number=line_num,
                            page_number=page_num,
                        )

                # Also extract table cells individually
                tables = page.extract_tables() or []
                for table_idx, table in enumerate(tables):
                    for row_idx, row in enumerate(table):
                        for col_idx, cell in enumerate(row or []):
                            if cell and str(cell).strip():
                                yield LeakerRecord(
                                    content=str(cell).strip(),
                                    source=source,
                                    source_type="pdf_table",
                                    page_number=page_num,
                                    extra={
                                        "table_index": table_idx,
                                        "row": row_idx,
                                        "col": col_idx,
                                    },
                                )

    def _extract_pypdf(self, source: str):
        from pypdf import PdfReader

        reader = PdfReader(source)
        for page_num, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for line_num, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    yield LeakerRecord(
                        content=line.strip(),
                        source=source,
                        source_type=self.source_type,
                        line_number=line_num,
                        page_number=page_num,
                    )
