"""
Searcher — queries Elasticsearch and returns structured results with
full provenance (source file, type, line, column, etc.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from elasticsearch import Elasticsearch

from config import cfg


@dataclass
class SearchResult:
    content: str
    source: str
    source_type: str
    line_number: Optional[int]
    column_name: Optional[str]
    table_name: Optional[str]
    sheet_name: Optional[str]
    page_number: Optional[int]
    score: float

    def display(self) -> str:
        loc_parts = []
        if self.table_name:
            loc_parts.append(f"table={self.table_name}")
        if self.sheet_name:
            loc_parts.append(f"sheet={self.sheet_name}")
        if self.page_number:
            loc_parts.append(f"page={self.page_number}")
        if self.line_number:
            loc_parts.append(f"line={self.line_number}")
        if self.column_name:
            loc_parts.append(f"col={self.column_name}")
        location = ", ".join(loc_parts) or "unknown location"

        return (
            f"  [{self.source_type}] {self.source}\n"
            f"  Location : {location}\n"
            f"  Content  : {self.content}\n"
            f"  Score    : {self.score:.4f}"
        )


class Searcher:
    def __init__(self, es: Elasticsearch, index_name: str | None = None):
        self.es = es
        self.index_name = index_name or f"{cfg.ES_INDEX_PREFIX}_data"

    def search(
        self,
        query: str,
        *,
        exact: bool = False,
        source_types: List[str] | None = None,
        sources: List[str] | None = None,
        size: int = 50,
        page: int = 1,
    ) -> List[SearchResult]:
        """
        Search across all indexed data.

        Parameters
        ----------
        query       : The search string (email, name, phone, keyword…)
        exact       : If True, use exact match (keyword field). Otherwise full-text.
        source_types: Filter to specific source types (e.g. ['csv', 'pdf'])
        sources     : Filter to specific source files/connections
        size        : Number of results per page
        page        : Page number (1-based)
        """
        must_clauses = []

        if exact:
            must_clauses.append({"term": {"content.keyword": query}})
        else:
            must_clauses.append({
                "multi_match": {
                    "query": query,
                    "fields": ["content^3", "column_name", "table_name", "source"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            })

        filter_clauses = []
        if source_types:
            filter_clauses.append({"terms": {"source_type": source_types}})
        if sources:
            filter_clauses.append({"terms": {"source": sources}})

        es_query = {
            "bool": {
                "must": must_clauses,
                **({"filter": filter_clauses} if filter_clauses else {}),
            }
        }

        from_ = (page - 1) * size
        resp = self.es.search(
            index=self.index_name,
            query=es_query,
            size=size,
            from_=from_,
            highlight={
                "fields": {"content": {}},
                "pre_tags": ["\033[1;33m"],
                "post_tags": ["\033[0m"],
            },
        )

        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            # Use highlighted content if available
            hl = hit.get("highlight", {}).get("content", [])
            content = hl[0] if hl else src.get("content", "")
            results.append(
                SearchResult(
                    content=content,
                    source=src.get("source", ""),
                    source_type=src.get("source_type", ""),
                    line_number=src.get("line_number"),
                    column_name=src.get("column_name"),
                    table_name=src.get("table_name"),
                    sheet_name=src.get("sheet_name"),
                    page_number=src.get("page_number"),
                    score=hit["_score"],
                )
            )
        return results

    def count(self, query: str) -> int:
        resp = self.es.count(
            index=self.index_name,
            query={"match": {"content": query}},
        )
        return resp["count"]

    def list_sources(self) -> List[dict]:
        resp = self.es.search(
            index=self.index_name,
            size=0,
            aggs={
                "by_source": {
                    "terms": {"field": "source", "size": 1000},
                    "aggs": {
                        "by_type": {"terms": {"field": "source_type", "size": 20}}
                    },
                }
            },
        )
        sources = []
        for bucket in resp["aggregations"]["by_source"]["buckets"]:
            types = [b["key"] for b in bucket["by_type"]["buckets"]]
            sources.append({"source": bucket["key"], "count": bucket["doc_count"], "types": types})
        return sources
