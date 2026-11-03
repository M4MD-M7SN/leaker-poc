"""
XML Extractor — flattens XML into text nodes with XPath provenance.
"""
from __future__ import annotations

from typing import Generator
import xml.etree.ElementTree as ET

from .base import BaseExtractor, LeakerRecord


class XMLExtractor(BaseExtractor):
    source_type = "xml"

    def extract(self, source: str) -> Generator[LeakerRecord, None, None]:
        try:
            tree = ET.parse(source)
            root = tree.getroot()
        except ET.ParseError as exc:
            yield LeakerRecord(
                content=f"[XML parse error] {exc}",
                source=source,
                source_type=self.source_type,
            )
            return

        yield from self._walk(root, source, path=root.tag, line=1)

    def _walk(self, element, source: str, path: str, line: int):
        text = (element.text or "").strip()
        if text:
            yield LeakerRecord(
                content=text,
                source=source,
                source_type=self.source_type,
                column_name=path,
            )

        for attr_name, attr_val in element.attrib.items():
            if attr_val.strip():
                yield LeakerRecord(
                    content=attr_val,
                    source=source,
                    source_type=self.source_type,
                    column_name=f"{path}@{attr_name}",
                )

        for child in element:
            child_path = f"{path}/{child.tag}"
            yield from self._walk(child, source, child_path, line)
