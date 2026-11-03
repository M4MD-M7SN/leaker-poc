#!/usr/bin/env python3
"""
Leaker CLI — index, search, watch, and analyze multi-format data sources.

PIPELINE OVERVIEW
-----------------
  [Raw files / Drop Zone]
        ↓
  [loader.py  — dispatches to the right extractor]
        ↓
  [extractors/ — parse & normalize → LeakerRecord objects]
        ↓
  [Elasticsearch — index / search]
        ↓
  [analytics.py — cluster, trend analysis, combo breakdown]

COMMANDS
--------
  index       Index one or more files / directories / glob patterns
  index-db    Index a live database (postgres, mysql, mongo, redis)
  watch       Start the Drop Zone watcher (auto-index anything dropped in)
  search      Full-text or exact search across all indexed data
  analyze     Cluster analysis: email domains, combo patterns, passwords
  sources     List all indexed sources and their document counts
  delete-index  Wipe the Elasticsearch index

Usage examples
--------------
  # Start Elasticsearch
  docker compose up -d

  # Drop zone — just drop files (including ZIPs) and they are auto-indexed
  python cli.py watch
  python cli.py watch --dropzone /mnt/dumps

  # Index specific files / directories
  python cli.py index data/breach.csv data/users.sqlite data/dump.sql
  python cli.py index /path/to/data/

  # Index a live database
  python cli.py index-db postgres --host localhost --db mydb --user postgres
  python cli.py index-db mongo --uri mongodb://localhost:27017 --db mydb

  # Search
  python cli.py search "user@gmail.com"
  python cli.py search "user@gmail.com" --exact
  python cli.py search "John Smith" --type csv --type sqlite
  python cli.py search "password123" --size 100

  # Analytics
  python cli.py analyze
  python cli.py analyze --topic domains
  python cli.py analyze --topic passwords --top 50

  # Sources overview
  python cli.py sources
"""
from __future__ import annotations

import sys
import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


@click.group()
def cli():
    """Leaker — multi-format data extraction and Elasticsearch search engine."""
    pass


# ── INDEX ──────────────────────────────────────────────────────────────────────

@cli.command("index")
@click.argument("paths", nargs=-1, required=True)
@click.option("--index", "index_name", default=None, help="Elasticsearch index name")
def index_files(paths, index_name):
    """Index one or more files / directories / glob patterns."""
    from indexer import get_es_client, Indexer
    from loader import extract_path

    es = get_es_client()
    idxr = Indexer(es, index_name)

    def _records():
        for path in paths:
            console.print(f"[cyan]Extracting:[/cyan] {path}")
            yield from extract_path(path)

    ok, err = idxr.index_records(_records())
    console.print(f"\n[green]Done:[/green] {ok:,} indexed, {err:,} errors")


@cli.command("index-db")
@click.argument("db_type", type=click.Choice(["postgres", "mysql", "mongo", "redis"]))
@click.option("--host", default="localhost")
@click.option("--port", type=int, default=None)
@click.option("--user", default=None)
@click.option("--password", default=None, prompt=True, hide_input=True)
@click.option("--db", "database", default=None)
@click.option("--uri", default=None, help="Full connection URI (mongo/redis)")
@click.option("--index", "index_name", default=None)
def index_db(db_type, host, port, user, password, database, uri, index_name):
    """Index a live database (postgres, mysql, mongo, redis)."""
    from indexer import get_es_client, Indexer

    es = get_es_client()
    idxr = Indexer(es, index_name)

    if db_type == "postgres":
        from extractors.postgres_extractor import PostgresExtractor
        extractor = PostgresExtractor(
            host=host, port=port or 5432, user=user or "postgres",
            password=password or "", database=database or "",
        )
        label = f"postgres://{host}/{database}"
    elif db_type == "mysql":
        from extractors.mysql_extractor import MySQLExtractor
        extractor = MySQLExtractor(
            host=host, port=port or 3306, user=user or "root",
            password=password or "", database=database or "",
        )
        label = f"mysql://{host}/{database}"
    elif db_type == "mongo":
        from extractors.mongo_extractor import MongoExtractor
        extractor = MongoExtractor(uri=uri or f"mongodb://{host}:27017", database=database or "")
        label = uri or f"mongodb://{host}/{database}"
    elif db_type == "redis":
        from extractors.redis_extractor import RedisExtractor
        extractor = RedisExtractor(host=host, port=port or 6379, password=password or "")
        label = f"redis://{host}"
    else:
        console.print(f"[red]Unknown db type: {db_type}[/red]")
        sys.exit(1)

    console.print(f"[cyan]Connecting to:[/cyan] {label}")
    ok, err = idxr.index_records(extractor.extract(label))
    console.print(f"\n[green]Done:[/green] {ok:,} indexed, {err:,} errors")


# ── SEARCH ─────────────────────────────────────────────────────────────────────

@cli.command("search")
@click.argument("query")
@click.option("--exact", is_flag=True, help="Exact match instead of full-text")
@click.option("--type", "source_types", multiple=True, help="Filter by source type")
@click.option("--source", "sources", multiple=True, help="Filter by source path/label")
@click.option("--size", default=20, show_default=True, help="Results per page")
@click.option("--page", default=1, show_default=True, help="Page number")
@click.option("--index", "index_name", default=None, help="Elasticsearch index name")
@click.option("--raw", is_flag=True, help="Plain output (no color/table)")
def search_cmd(query, exact, source_types, sources, size, page, index_name, raw):
    """Search all indexed data for QUERY."""
    from indexer import get_es_client
    from search import Searcher

    es = get_es_client()
    searcher = Searcher(es, index_name)

    total = searcher.count(query)
    results = searcher.search(
        query,
        exact=exact,
        source_types=list(source_types) or None,
        sources=list(sources) or None,
        size=size,
        page=page,
    )

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    console.print(f"\n[bold]Query:[/bold] {query}  |  "
                  f"[bold]Total hits:[/bold] {total:,}  |  "
                  f"[bold]Showing:[/bold] {len(results)} (page {page})\n")

    if raw:
        for r in results:
            print(r.display())
            print()
        return

    table = Table(
        "Source", "Type", "Location", "Content", "Score",
        box=box.ROUNDED,
        show_lines=True,
        highlight=True,
    )
    for r in results:
        loc_parts = []
        if r.table_name: loc_parts.append(f"table: {r.table_name}")
        if r.sheet_name: loc_parts.append(f"sheet: {r.sheet_name}")
        if r.page_number: loc_parts.append(f"page: {r.page_number}")
        if r.line_number: loc_parts.append(f"line: {r.line_number}")
        if r.column_name: loc_parts.append(f"col: {r.column_name}")
        location = "\n".join(loc_parts) or "-"

        table.add_row(
            r.source,
            r.source_type,
            location,
            r.content[:200],
            f"{r.score:.3f}",
        )

    console.print(table)


# ── SOURCES ────────────────────────────────────────────────────────────────────

@cli.command("sources")
@click.option("--index", "index_name", default=None)
def list_sources(index_name):
    """List all indexed sources and their document counts."""
    from indexer import get_es_client
    from search import Searcher

    es = get_es_client()
    searcher = Searcher(es, index_name)
    sources = searcher.list_sources()

    table = Table("Source", "Types", "Documents", box=box.ROUNDED)
    for s in sources:
        table.add_row(s["source"], ", ".join(s["types"]), f"{s['count']:,}")
    console.print(table)


# ── DELETE INDEX ───────────────────────────────────────────────────────────────

@cli.command("delete-index")
@click.option("--index", "index_name", default=None)
@click.confirmation_option(prompt="Are you sure you want to delete the index?")
def delete_index(index_name):
    """Delete the Elasticsearch index (wipe all indexed data)."""
    from indexer import get_es_client
    from config import cfg

    es = get_es_client()
    name = index_name or f"{cfg.ES_INDEX_PREFIX}_data"
    es.indices.delete(index=name, ignore_unavailable=True)
    console.print(f"[red]Deleted index:[/red] {name}")


# ── WATCH (Drop Zone) ──────────────────────────────────────────────────────────

@cli.command("watch")
@click.option(
    "--dropzone",
    default="dropzone",
    show_default=True,
    help="Directory to watch.  Created automatically if it doesn't exist.",
)
@click.option(
    "--index", "index_name", default=None,
    help="Elasticsearch index name.",
)
@click.option(
    "--settle", "settle_seconds", default=2.0, show_default=True,
    help="Seconds to wait after a file appears before processing it.",
)
@click.option(
    "--no-move", "no_move", is_flag=True, default=False,
    help="Keep files in the drop zone instead of moving them to processed/.",
)
def watch_cmd(dropzone, index_name, settle_seconds, no_move):
    """
    Start the Drop Zone watcher.

    Drop ANY files (including ZIP / TAR / 7z archives) into the watch
    directory.  Each file is automatically:

    \b
      1. Unpacked  (if it's an archive)
      2. Parsed    (by the correct extractor for its format)
      3. Indexed   into Elasticsearch
      4. Moved     to processed/  (unless --no-move)

    Press Ctrl-C to stop.
    """
    from pathlib import Path
    from indexer import get_es_client, Indexer
    from watcher import start_watcher

    es   = get_es_client()
    idxr = Indexer(es, index_name)

    console.print(f"\n[bold cyan]Leaker Drop Zone[/bold cyan]")
    console.print(f"[dim]Watching:[/dim] [green]{Path(dropzone).resolve()}[/green]")
    console.print(
        "[dim]Supports:[/dim] CSV, TXT, PDF, JSON, XML, Excel, SQLite, SQL, "
        "DOCX + ZIP/TAR/GZ/7z archives\n"
    )

    start_watcher(
        index_fn=lambda records: idxr.index_records(records),
        dropzone=Path(dropzone),
        settle_seconds=settle_seconds,
        move_after=not no_move,
        block=True,
    )


# ── ANALYZE ────────────────────────────────────────────────────────────────────

@cli.command("analyze")
@click.option(
    "--topic",
    type=click.Choice([
        "all",       # full auto report (default)
        "fields",    # what field types exist and their counts
        "domains",   # email domain clustering
        "passwords", # most common passwords
        "phones",    # phone prefix clustering
        "ips",       # IP /24 subnet clustering
        "hashes",    # hash algorithm breakdown
        "usernames", # most common usernames
        "sources",   # records per source file
        "field",     # deep-dive into one specific field type (use with --field-type)
    ]),
    default="all",
    show_default=True,
    help="Which analysis to run.",
)
@click.option(
    "--field-type", "field_type", default=None,
    help="Field type for --topic field  (e.g. name, address, user_id …)",
)
@click.option(
    "--top", "top_n",
    default=20, show_default=True,
    help="How many results to show per category.",
)
@click.option("--index", "index_name", default=None, help="Elasticsearch index name.")
def analyze_cmd(topic, field_type, top_n, index_name):
    """
    Cluster and trend analysis on indexed data.

    The report is DATA-DRIVEN — it detects what field types (email, phone,
    ip_address, username, hash, password, name, address, …) actually exist
    in the index and runs the most appropriate analysis for each one.

    \b
    Topics
    ------
      all       Full auto report (adapts to whatever is in the index)
      fields    List every field type found and its record count
      domains   Email domain clustering  (gmail.com, yahoo.com, …)
      passwords Most common plaintext passwords
      phones    Phone prefix clustering  (+1-415, +44-20, …)
      ips       IP /24 subnet clustering  (192.168.1.0/24, …)
      hashes    Hash algorithm breakdown  (MD5, SHA-1, SHA-256, bcrypt, …)
      usernames Most common usernames
      sources   Record counts and types per source file
      field     Deep-dive into one field type  (use --field-type NAME)

    \b
    Examples
    --------
      python cli.py analyze
      python cli.py analyze --topic domains
      python cli.py analyze --topic field --field-type address
      python cli.py analyze --topic passwords --top 50
    """
    from indexer import get_es_client
    from config import cfg
    from analytics import (
        Analytics,
        display_full_report,
        display_field_types,
        display_field_report,
        display_sources,
        FieldReport,
    )

    es    = get_es_client()
    index = index_name or f"{cfg.ES_INDEX_PREFIX}_data"
    ana   = Analytics(es, index)

    if topic == "all":
        display_full_report(ana.full_report(top_n))

    elif topic == "fields":
        display_field_types(ana.field_types(top_n))

    elif topic == "domains":
        r = FieldReport(field_type="email", count=0,
                        clusters=ana.email_domains(top_n))
        display_field_report(r)

    elif topic == "passwords":
        r = FieldReport(field_type="password", count=0,
                        top_values=ana.top_values("password", top_n, skip_hashes=True))
        display_field_report(r)

    elif topic == "phones":
        r = FieldReport(field_type="phone", count=0,
                        clusters=ana.phone_prefixes(top_n),
                        top_values=ana.top_values("phone", top_n))
        display_field_report(r)

    elif topic == "ips":
        r = FieldReport(field_type="ip_address", count=0,
                        clusters=ana.ip_subnets(top_n))
        display_field_report(r)

    elif topic == "hashes":
        r = FieldReport(field_type="hash", count=0,
                        hash_types=ana.hash_types(top_n))
        display_field_report(r)

    elif topic == "usernames":
        r = FieldReport(field_type="username", count=0,
                        top_values=ana.top_values("username", top_n))
        display_field_report(r)

    elif topic == "sources":
        display_sources(ana.source_stats(top_n))

    elif topic == "field":
        if not field_type:
            console.print("[red]--field-type is required for --topic field[/red]")
            console.print("  Example: python cli.py analyze --topic field --field-type address")
            return
        # Get count for this field type
        types = {f.field_type: f.count for f in ana.field_types(200)}
        count = types.get(field_type, 0)
        if count == 0:
            console.print(f"[yellow]No records found for field type:[/yellow] {field_type}")
            return
        r = ana.analyse_field(field_type, count, top_n)
        display_field_report(r)


if __name__ == "__main__":
    cli()
