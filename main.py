#!/usr/bin/env python3
"""
main.py — Leaker entry point.

Default mode (no args):  interactive REPL — type anything to search.
Non-interactive commands: index, index-db, sources, delete.

How the flow works
──────────────────
  leak                         → interactive REPL shell
  leak index  <paths …>        → extract files → bulk index → report
  leak index-db <type> [opts]  → extract live DB → bulk index → report
  leak sources                 → aggregate indexed sources → display
  leak delete                  → wipe ES index

Interactive commands (inside the REPL)
───────────────────────────────────────
  <anything>              search across all indexed data
  :exact                  toggle exact-match mode  (on / off)
  :type csv sqlite …      restrict results to these source types
  :type                   clear type filter
  :size 50                set results-per-page (default 20)
  :sources                list all indexed sources
  :index <path …>         index files / directories without leaving the shell
  :help                   show this help
  :exit  /  q  /  Ctrl-C  quit
"""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import functions as fn

console = Console()

BANNER = r"""
  ██╗     ███████╗ █████╗ ██╗  ██╗███████╗██████╗
  ██║     ██╔════╝██╔══██╗██║ ██╔╝██╔════╝██╔══██╗
  ██║     █████╗  ███████║█████╔╝ █████╗  ██████╔╝
  ██║     ██╔══╝  ██╔══██║██╔═██╗ ██╔══╝  ██╔══██╗
  ███████╗███████╗██║  ██║██║  ██╗███████╗██║  ██║
  ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
"""

HELP_TEXT = """
[bold]Search[/bold]  — type anything:
  alice@gmail.com          full-text search (fuzzy)
  @hotmail.com             partial match across all sources
  555-1234                 phone, hash, keyword — anything

[bold]Session commands[/bold]  (prefix with :)
  :exact                   toggle exact-match mode
  :type csv sqlite …       filter results by source type
  :type                    clear the type filter
  :size <n>                results per page (default 20)
  :sources                 list all indexed sources
  :index <path …>          index files / dirs without leaving the shell
  :help                    show this message
  :exit  |  q              quit
"""


# ══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE REPL
# ══════════════════════════════════════════════════════════════════════════════

def run_interactive(index_name: str = fn.ES_INDEX) -> None:
    """
    Start the interactive Leaker shell.

    Flow each iteration:
      1. Read input from the user
      2. Detect whether it is a session command (:cmd) or a search query
      3a. Command → mutate session state or perform an action
      3b. Query   → count_hits → search → display_results
    """
    # ── readline history (best-effort) ────────────────────────────────────────
    try:
        import readline
        import atexit
        history_file = os.path.expanduser("~/.leak_history")
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass
        readline.set_history_length(1000)
        atexit.register(readline.write_history_file, history_file)
    except ImportError:
        pass

    # ── connect ───────────────────────────────────────────────────────────────
    es = fn.get_es_client()

    # Confirm ES is reachable
    try:
        info = es.info()
        es_version = info["version"]["number"]
    except Exception as exc:
        console.print(f"[red]Cannot reach Elasticsearch:[/red] {exc}")
        console.print(
            "Start it with:  [bold]docker compose up -d[/bold]"
        )
        sys.exit(1)

    # Doc count for the banner
    try:
        doc_count = es.count(index=index_name)["count"]
        doc_str   = f"{doc_count:,}"
    except Exception:
        doc_str = "0 (index not yet created)"

    # ── banner ────────────────────────────────────────────────────────────────
    console.print(f"[bold cyan]{BANNER}[/bold cyan]")
    console.print(
        Panel(
            f"[green]Elasticsearch {es_version}[/green]   "
            f"[dim]index:[/dim] [bold]{index_name}[/bold]   "
            f"[dim]docs:[/dim] [bold]{doc_str}[/bold]\n\n"
            "[dim]Type anything to search.  "
            ":help for commands.  "
            ":exit to quit.[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    # ── session state ─────────────────────────────────────────────────────────
    exact        = False          # fuzzy by default
    source_types: list[str] = []  # empty = no filter
    page_size    = 20

    # ── REPL loop ─────────────────────────────────────────────────────────────
    while True:
        # Build a prompt that shows active filters
        mode_tag  = "[magenta]EXACT[/magenta] " if exact else ""
        types_tag = (
            f"[yellow]type:{','.join(source_types)}[/yellow] "
            if source_types else ""
        )
        prompt_str = f"{mode_tag}{types_tag}[bold cyan]leak>[/bold cyan] "
        # rich can't render inline prompts, so strip markup for input()
        prompt_plain = (
            ("EXACT " if exact else "")
            + (f"type:{','.join(source_types)} " if source_types else "")
            + "leak> "
        )

        try:
            console.print(prompt_str, end="")
            raw = input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye.[/dim]")
            break

        query = raw.strip()
        if not query:
            continue

        # ── quit ──────────────────────────────────────────────────────────────
        if query in (":exit", ":quit", "q", "exit", "quit"):
            console.print("[dim]bye.[/dim]")
            break

        # ── session commands ───────────────────────────────────────────────────
        if query.startswith(":"):
            parts   = query[1:].split()
            cmd     = parts[0].lower() if parts else ""
            args    = parts[1:]

            # :help
            if cmd == "help":
                console.print(HELP_TEXT)

            # :exact  — toggle
            elif cmd == "exact":
                exact = not exact
                state = "[green]ON[/green]" if exact else "[yellow]OFF[/yellow]"
                console.print(f"  Exact-match mode: {state}")

            # :type csv sqlite …  — set filter   |  :type alone clears it
            elif cmd == "type":
                if args:
                    source_types = args
                    console.print(
                        f"  Type filter set: [yellow]{', '.join(source_types)}[/yellow]"
                    )
                else:
                    source_types = []
                    console.print("  Type filter cleared.")

            # :size 50
            elif cmd == "size":
                if args and args[0].isdigit():
                    page_size = int(args[0])
                    console.print(f"  Page size set to [bold]{page_size}[/bold]")
                else:
                    console.print(f"  Current page size: [bold]{page_size}[/bold]")

            # :sources
            elif cmd == "sources":
                sources = fn.list_sources(es, index=index_name)
                fn.display_sources(sources)

            # :index <path …>
            elif cmd == "index":
                if not args:
                    console.print("  Usage: [bold]:index <path> [path …][/bold]")
                else:
                    def _records():
                        for p in args:
                            console.print(f"  [cyan]Extracting:[/cyan] {p}")
                            yield from fn.extract_path(p)

                    ok, err = fn.index_records(es, _records(), index=index_name)
                    console.print(
                        f"  [green]Done.[/green]  "
                        f"Indexed: [bold]{ok:,}[/bold]  "
                        f"Errors: [bold red]{err}[/bold red]"
                    )

            else:
                console.print(
                    f"  [red]Unknown command:[/red] :{cmd}  "
                    "(type [bold]:help[/bold] for a list)"
                )

            continue

        # ── search ─────────────────────────────────────────────────────────────
        #
        # Flow:
        #   1. count_hits  — lightweight ES count query (shows total matches)
        #   2. search      — paginated results with highlighting
        #   3. display_results — rich table or plain text
        #
        try:
            total   = fn.count_hits(es, query, index=index_name)
            results = fn.search(
                es,
                query,
                exact        = exact,
                source_types = source_types or None,
                size         = page_size,
                page         = 1,
                index        = index_name,
            )
            fn.display_results(results, query, total, page=1, raw=False)

        except Exception as exc:
            console.print(f"[red]Search error:[/red] {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# NON-INTERACTIVE CLI COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.option("--index", "index_name", default=fn.ES_INDEX,
              show_default=True, help="Elasticsearch index name")
@click.pass_context
def cli(ctx, index_name):
    """
    Leaker — index your data, search it all at once.

    Run with no subcommand to open the interactive shell.
    """
    ctx.ensure_object(dict)
    ctx.obj["index"] = index_name

    # No subcommand → drop into interactive REPL
    if ctx.invoked_subcommand is None:
        run_interactive(index_name)


# ── index (files / dirs / globs) ─────────────────────────────────────────────

@cli.command("index")
@click.argument("paths", nargs=-1, required=True)
@click.option("--index", "index_name", default=fn.ES_INDEX, show_default=True)
@click.option("--no-progress", is_flag=True)
def cmd_index(paths, index_name, no_progress):
    """
    Index files, directories, or glob patterns.

    \b
    Examples:
      leak index data/breach.csv
      leak index data/users.db data/dump.sql
      leak index /data/exports/
      leak index "dumps/**/*.csv"
    """
    es = fn.get_es_client()

    def records():
        for path in paths:
            console.print(f"[cyan]  Extracting:[/cyan] {path}")
            yield from fn.extract_path(path)

    console.print(f"\n[bold]Indexing into:[/bold] {index_name}\n")
    ok, err = fn.index_records(es, records(), index=index_name,
                                show_progress=not no_progress)
    console.print(
        f"\n[green]Done.[/green]  "
        f"Indexed: [bold]{ok:,}[/bold]  "
        f"Errors: [bold red]{err}[/bold red]"
    )


# ── index-db (live databases) ─────────────────────────────────────────────────

@cli.command("index-db")
@click.argument("db_type",
                type=click.Choice(["postgres", "mysql", "mongo", "redis"],
                                  case_sensitive=False))
@click.option("--host",     default="localhost", show_default=True)
@click.option("--port",     type=int, default=None)
@click.option("--user",     default=None)
@click.option("--password", default="")
@click.option("--db",       "database", default=None)
@click.option("--uri",      default=None,       help="Full URI (mongo / redis)")
@click.option("--schemas",  multiple=True,      help="PostgreSQL schemas [repeatable]")
@click.option("--index",    "index_name", default=fn.ES_INDEX, show_default=True)
@click.option("--no-progress", is_flag=True)
def cmd_index_db(db_type, host, port, user, password, database,
                 uri, schemas, index_name, no_progress):
    """
    Extract and index a live database.

    \b
    Examples:
      leak index-db postgres --host localhost --db mydb --user postgres
      leak index-db mysql    --host localhost --db mydb --user root
      leak index-db mongo    --uri mongodb://localhost:27017 --db mydb
      leak index-db redis    --host localhost
    """
    db_type = db_type.lower()

    if db_type == "postgres":
        label   = f"postgres://{host}/{database}"
        records = fn.extract_postgres(
            host=host, port=port or 5432,
            user=user or fn.PG_USER, password=password or fn.PG_PASSWORD,
            database=database or fn.PG_DATABASE,
            schemas=list(schemas) or None,
        )
    elif db_type == "mysql":
        label   = f"mysql://{host}/{database}"
        records = fn.extract_mysql(
            host=host, port=port or 3306,
            user=user or fn.MYSQL_USER, password=password or fn.MYSQL_PASSWORD,
            database=database or fn.MYSQL_DATABASE,
        )
    elif db_type == "mongo":
        effective_uri = uri or f"mongodb://{host}:{port or 27017}"
        label         = effective_uri
        records       = fn.extract_mongo(
            uri=effective_uri,
            database=database or fn.MONGO_DATABASE,
        )
    elif db_type == "redis":
        label   = f"redis://{host}:{port or 6379}"
        records = fn.extract_redis(
            host=host, port=port or int(fn.REDIS_PORT),
            password=password or fn.REDIS_PASSWORD,
        )

    es = fn.get_es_client()
    console.print(f"\n[bold]Connecting to:[/bold] {label}")
    console.print(f"[bold]Indexing into:[/bold] {index_name}\n")
    ok, err = fn.index_records(es, records, index=index_name,
                                show_progress=not no_progress)
    console.print(
        f"\n[green]Done.[/green]  "
        f"Indexed: [bold]{ok:,}[/bold]  "
        f"Errors: [bold red]{err}[/bold red]"
    )


# ── sources ───────────────────────────────────────────────────────────────────

@cli.command("sources")
@click.option("--index", "index_name", default=fn.ES_INDEX, show_default=True)
def cmd_sources(index_name):
    """List all indexed sources with document counts."""
    es = fn.get_es_client()
    fn.display_sources(fn.list_sources(es, index=index_name))


# ── delete ────────────────────────────────────────────────────────────────────

@cli.command("delete")
@click.option("--index", "index_name", default=fn.ES_INDEX, show_default=True)
@click.option("--yes", is_flag=True, help="Skip confirmation")
def cmd_delete(index_name, yes):
    """Delete the Elasticsearch index (wipes all data)."""
    if not yes:
        click.confirm(
            f"Delete index '{index_name}'? This cannot be undone.",
            abort=True,
        )
    es = fn.get_es_client()
    fn.delete_index(es, index=index_name)
    console.print(f"[red]Deleted index:[/red] {index_name}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cli()
