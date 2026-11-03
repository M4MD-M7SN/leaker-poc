"""
JSON / JSONL Extractor.

- Regular JSON: flattens nested objects, yields one record per leaf value.
- JSONL (one JSON object per line): processes each line independently.
"""
from __future__ import annotations

import json
from typing import Any, Generator

from .base import BaseExtractor, LeakerRecord


class JSONExtractor(BaseExtractor):
    source_type = "json"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        with open(source, encoding="utf-8", errors="replace") as fh:
            first_char = fh.read(1)
            fh.seek(0)

            if source.endswith(".jsonl") or source.endswith(".ndjson"):
                yield from self._extract_jsonl(source, fh)
            else:
                yield from self._extract_json(source, fh)

    def _extract_json(self, source: str, fh):
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            yield LeakerRecord(
                content=f"[JSON parse error] {exc}",
                source=source,
                source_type=self.source_type,
                line_number=exc.lineno,
            )
            return

        if isinstance(data, list):
            for idx, item in enumerate(data, start=1):
                yield from self._flatten(item, source, line_number=idx)
        else:
            yield from self._flatten(data, source, line_number=1)

    def _extract_jsonl(self, source: str, fh):
        for line_num, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                yield from self._flatten(obj, source, line_number=line_num)
            except json.JSONDecodeError:
                yield LeakerRecord(
                    content=line,
                    source=source,
                    source_type="jsonl",
                    line_number=line_num,
                )

    def _flatten(
        self,
        obj: Any,
        source: str,
        prefix: str = "",
        line_number: int = 1,
    ) -> Generator[LeakerRecord, None, None]:
        if isinstance(obj, dict):
            for key, val in obj.items():
                yield from self._flatten(
                    val, source, f"{prefix}.{key}" if prefix else key, line_number
                )
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                yield from self._flatten(
                    item, source, f"{prefix}[{idx}]", line_number
                )
        else:
            val_str = str(obj).strip()
            if val_str:
                yield LeakerRecord(
                    content=val_str,
                    source=source,
                    source_type=self.source_type,
                    line_number=line_number,
                    column_name=prefix,
                )
