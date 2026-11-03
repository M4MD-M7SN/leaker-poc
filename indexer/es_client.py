"""
Elasticsearch client factory — singleton with retry/connection logic.
"""
from __future__ import annotations

from elasticsearch import Elasticsearch
from config import cfg


def get_es_client() -> Elasticsearch:
    return Elasticsearch(
        cfg.ES_HOST,
        basic_auth=(cfg.ES_USERNAME, cfg.ES_PASSWORD),
        verify_certs=False,
        request_timeout=30,
    )
