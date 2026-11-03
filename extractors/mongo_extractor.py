"""
MongoDB Extractor — iterates all collections, all documents.
"""
from __future__ import annotations

from typing import Generator, Any

from .base import BaseExtractor, LeakerRecord


class MongoExtractor(BaseExtractor):
    source_type = "mongodb"

    def __init__(self, uri: str, database: str):
        self.uri = uri
        self.database = database

    def extract(self, source: str = "") -> Generator[LeakerRecord, None, None]:
        from pymongo import MongoClient

        label = source or self.uri
        client = MongoClient(self.uri)
        db = client[self.database]
        try:
            for collection_name in db.list_collection_names():
                collection = db[collection_name]
                for row_num, doc in enumerate(collection.find(), start=1):
                    doc.pop("_id", None)
                    yield from self._flatten_doc(
                        doc, label, collection_name, row_num
                    )
        finally:
            client.close()

    def _flatten_doc(
        self,
        obj: Any,
        source: str,
        collection: str,
        row_num: int,
        prefix: str = "",
    ) -> Generator[LeakerRecord, None, None]:
        if isinstance(obj, dict):
            for key, val in obj.items():
                yield from self._flatten_doc(
                    val, source, collection, row_num,
                    f"{prefix}.{key}" if prefix else key,
                )
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                yield from self._flatten_doc(
                    item, source, collection, row_num, f"{prefix}[{idx}]"
                )
        else:
            val_str = str(obj).strip()
            if val_str:
                yield LeakerRecord(
                    content=val_str,
                    source=source,
                    source_type=self.source_type,
                    line_number=row_num,
                    column_name=prefix,
                    table_name=collection,
                )
