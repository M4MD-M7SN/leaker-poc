"""
Indexer — takes LeakerRecord generators and bulk-loads them into Elasticsearch.

Index mapping is created on first use and is designed for fast full-text
and exact-value searches.
"""
from __future__ import annotations

import sys
from typing import Generator, Iterable

from elasticsearch import Elasticsearch
from elasticsearch.helpers import streaming_bulk
from tqdm import tqdm

from extractors.base import LeakerRecord
from config import cfg

# ── Index Mapping ──────────────────────────────────────────────────────────────
INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "email_analyzer": {
                    "type": "custom",
                    "tokenizer": "uax_url_email",
                    "filter": ["lowercase"],
                },
            }
        },
    },
    "mappings": {
        "properties": {
            "content":      {"type": "text",    "analyzer": "email_analyzer",
                             "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "source":       {"type": "keyword"},
            "source_type":  {"type": "keyword"},
            "line_number":  {"type": "integer"},
            "column_name":  {"type": "keyword"},
            "table_name":   {"type": "keyword"},
            "sheet_name":   {"type": "keyword"},
            "page_number":  {"type": "integer"},
            "doc_id":       {"type": "keyword"},
            "extra":        {"type": "object", "enabled": False},
        }
    },
}


class Indexer:
    def __init__(self, es: Elasticsearch, index_name: str | None = None):
        self.es = es
        self.index_name = index_name or f"{cfg.ES_INDEX_PREFIX}_data"
        self._ensure_index()

    def _ensure_index(self):
        if not self.es.indices.exists(index=self.index_name):
            self.es.indices.create(index=self.index_name, body=INDEX_MAPPING)
            print(f"[+] Created index: {self.index_name}")

    def index_records(
        self,
        records: Iterable[LeakerRecord],
        show_progress: bool = True,
    ) -> tuple[int, int]:
        """Bulk-index records. Returns (success_count, error_count)."""

        def _actions():
            for rec in records:
                doc = rec.to_dict()
                yield {
                    "_index": self.index_name,
                    "_id": doc["doc_id"],
                    "_source": doc,
                }

        success = 0
        errors = 0
        gen = _actions()
        if show_progress:
            gen = tqdm(gen, desc="Indexing", unit=" docs", file=sys.stdout)

        for ok, info in streaming_bulk(
            self.es,
            gen,
            chunk_size=cfg.ES_BATCH_SIZE,
            raise_on_error=False,
        ):
            if ok:
                success += 1
            else:
                errors += 1
                print(f"[!] Index error: {info}", file=sys.stderr)

        return success, errors
