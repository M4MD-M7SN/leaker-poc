"""
TXT / LOG Extractor — one record per non-empty line.
"""
from __future__ import annotations

from typing import Generator

from .base import BaseExtractor, LeakerRecord


class TXTExtractor(BaseExtractor):
    source_type = "txt"

    def __init__(self, encoding: str = "utf-8", errors: str = "replace"):
        self.encoding = encoding
        self.errors = errors

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        with open(source, encoding=self.encoding, errors=self.errors) as fh:
            for line_num, line in enumerate(fh, start=1):
                stripped = line.rstrip("\n\r")
                if stripped.strip():
                    yield LeakerRecord(
                        content=stripped,
                        source=source,
                        source_type=self.source_type,
                        line_number=line_num,
                    )
