"""
Base extractor interface.  Every extractor yields LeakerRecord objects.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Generator, Optional


@dataclass
class LeakerRecord:
    """One unit of indexed data — a row, line, or document chunk."""

    # Content
    content: str                          # The raw text / value

    # Provenance
    source: str                           # File path or connection string label
    source_type: str                      # csv | pdf | txt | json | sqlite | postgres | …
    line_number: Optional[int] = None     # Line / row number (1-based)
    column_name: Optional[str] = None     # Column / field name when applicable
    table_name: Optional[str] = None      # DB table / collection name
    sheet_name: Optional[str] = None      # Excel sheet or similar
    page_number: Optional[int] = None     # PDF page
    extra: dict = field(default_factory=dict)  # Additional metadata

    @property
    def doc_id(self) -> str:
        """Deterministic ID so re-indexing is idempotent."""
        raw = f"{self.source}:{self.source_type}:{self.line_number}:{self.content[:64]}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["doc_id"] = self.doc_id
        return d


class BaseExtractor:
    """All extractors implement `extract(source) -> Generator[LeakerRecord]`."""

    source_type: str = "unknown"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        raise NotImplementedError
