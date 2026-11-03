"""
Central configuration — reads from environment / .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Elasticsearch ──────────────────────────────────────────
    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_USERNAME: str = os.getenv("ES_USERNAME", "elastic")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "changeme")
    ES_INDEX_PREFIX: str = os.getenv("ES_INDEX_PREFIX", "leaker")
    ES_BATCH_SIZE: int = int(os.getenv("ES_BATCH_SIZE", "500"))

    # ── PostgreSQL ─────────────────────────────────────────────
    PG_HOST: str = os.getenv("PG_HOST", "localhost")
    PG_PORT: int = int(os.getenv("PG_PORT", "5432"))
    PG_USER: str = os.getenv("PG_USER", "postgres")
    PG_PASSWORD: str = os.getenv("PG_PASSWORD", "")
    PG_DATABASE: str = os.getenv("PG_DATABASE", "")

    # ── MongoDB ────────────────────────────────────────────────
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DATABASE: str = os.getenv("MONGO_DATABASE", "")

    # ── MySQL ──────────────────────────────────────────────────
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "")

    # ── Redis ──────────────────────────────────────────────────
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")


cfg = Config()
