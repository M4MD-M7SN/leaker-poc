"""
Redis Extractor — dumps all keys and their values.
Supports strings, hashes, lists, sets, sorted sets.
"""
from __future__ import annotations

from typing import Generator

from .base import BaseExtractor, LeakerRecord


class RedisExtractor(BaseExtractor):
    source_type = "redis"

    def __init__(self, host: str = "localhost", port: int = 6379, password: str = "", db: int = 0):
        self.host = host
        self.port = port
        self.password = password
        self.db = db

    def extract(self, source: str = "") -> Generator[LeakerRecord, None, None]:
        import redis

        label = source or f"redis://{self.host}:{self.port}/{self.db}"
        r = redis.Redis(
            host=self.host,
            port=self.port,
            password=self.password or None,
            db=self.db,
            decode_responses=True,
        )
        for key in r.scan_iter("*"):
            key_type = r.type(key)
            if key_type == "string":
                val = r.get(key) or ""
                if val.strip():
                    yield LeakerRecord(
                        content=val,
                        source=label,
                        source_type=self.source_type,
                        column_name=key,
                    )
            elif key_type == "hash":
                for field, val in r.hgetall(key).items():
                    if val.strip():
                        yield LeakerRecord(
                            content=val,
                            source=label,
                            source_type=self.source_type,
                            column_name=f"{key}:{field}",
                        )
            elif key_type == "list":
                for idx, val in enumerate(r.lrange(key, 0, -1)):
                    if val.strip():
                        yield LeakerRecord(
                            content=val,
                            source=label,
                            source_type=self.source_type,
                            column_name=f"{key}[{idx}]",
                        )
            elif key_type in ("set", "zset"):
                members = r.smembers(key) if key_type == "set" else r.zrange(key, 0, -1)
                for val in members:
                    if val.strip():
                        yield LeakerRecord(
                            content=val,
                            source=label,
                            source_type=self.source_type,
                            column_name=key,
                        )
