"""
watcher.py — Drop Zone Watcher  (Pre-Elasticsearch Organizer)
==============================================================

ARCHITECTURE
------------

  [Drop Zone dir]  →  [Watcher]  →  [Extractor / Parser]  →  [Elasticsearch]
  (user dumps)        (this file)    (extractors/)              (indexer/)

The DROP ZONE is a single directory where users dump any mix of raw files.
This module is the bridge: it watches the directory, unpacks archives, and
feeds every file through the parse → index pipeline automatically.

FLOW
----
  1. User drops ANY files into the drop zone (CSV, SQL, ZIP, TXT, PDF …)
  2. Watchdog detects each new file via filesystem events
  3. Archives (zip / tar / gz / 7z) are extracted into a staging subfolder
  4. Each file is dispatched to the correct extractor (see loader.py)
  5. Records are streamed into Elasticsearch in bulk
  6. Processed files move to  processed/  — drop zone stays clean

NESTED ARCHIVES
---------------
  If an archive contains other archives they are recursively unpacked.
  Depth is capped at MAX_ARCHIVE_DEPTH to prevent zip-bomb abuse.

USAGE
-----
  python cli.py watch                      # default: ./dropzone
  python cli.py watch --dropzone /mnt/data # custom path
  python cli.py watch --no-move            # keep files in place after indexing
"""
from __future__ import annotations

import logging
import os
import shutil
import tarfile
import time
import zipfile
from pathlib import Path
from threading import Lock, Thread
from typing import Callable, Generator

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from extractors.base import LeakerRecord
from loader import extract_file

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
DEFAULT_DROPZONE = Path("dropzone")
STAGING_DIR      = Path("dropzone") / "_staging"   # unpacked archives land here
PROCESSED_DIR    = Path("processed")               # done files move here

# ── Archive support ────────────────────────────────────────────────────────────
ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".tgz", ".bz2",
    ".tar.gz", ".tar.bz2", ".tar.xz", ".7z",
}

MAX_ARCHIVE_DEPTH = 4   # guard against nested zip bombs


# ══════════════════════════════════════════════════════════════════════════════
# 1. ARCHIVE UNPACKER
# ══════════════════════════════════════════════════════════════════════════════

def is_archive(path: Path) -> bool:
    """Return True if this file looks like an archive we can unpack."""
    name = path.name.lower()
    return (
        path.suffix.lower() in ARCHIVE_EXTENSIONS
        or name.endswith(".tar.gz")
        or name.endswith(".tar.bz2")
        or name.endswith(".tar.xz")
    )


def unpack_archive(archive_path: Path, dest_dir: Path) -> list[Path]:
    """
    Unpack a ZIP, TAR, GZ, or 7z archive into dest_dir.
    Returns a flat list of all extracted file paths (directories excluded).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    try:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Filter out paths with directory traversal attempts
                safe_names = [
                    n for n in zf.namelist()
                    if not os.path.isabs(n) and ".." not in n
                ]
                for name in safe_names:
                    zf.extract(name, dest_dir)
                extracted = [dest_dir / n for n in safe_names if not n.endswith("/")]
            logger.info("ZIP  unpacked: %s  →  %d files", archive_path.name, len(extracted))

        elif tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as tf:
                # Only extract regular files; skip absolute paths / traversal
                members = [
                    m for m in tf.getmembers()
                    if m.isfile()
                    and not os.path.isabs(m.name)
                    and ".." not in m.name
                ]
                tf.extractall(dest_dir, members=members)
                extracted = [dest_dir / m.name for m in members]
            logger.info("TAR  unpacked: %s  →  %d files", archive_path.name, len(extracted))

        else:
            # Try 7-zip (optional — install py7zr)
            try:
                import py7zr
                with py7zr.SevenZipFile(archive_path, mode="r") as sz:
                    sz.extractall(path=dest_dir)
                extracted = [p for p in dest_dir.rglob("*") if p.is_file()]
                logger.info("7z   unpacked: %s  →  %d files", archive_path.name, len(extracted))
            except ImportError:
                logger.warning(
                    "py7zr not installed — skipping 7z file: %s  "
                    "(run: pip install py7zr)", archive_path.name
                )
            except Exception as exc:
                logger.warning("7z unpack failed for %s: %s", archive_path.name, exc)

    except Exception as exc:
        logger.error("Archive unpack error for %s: %s", archive_path.name, exc)

    return [p for p in extracted if p.is_file()]


# ══════════════════════════════════════════════════════════════════════════════
# 2. PIPELINE RUNNER — parse one file, index everything it yields
# ══════════════════════════════════════════════════════════════════════════════

def process_file(
    path: Path,
    index_fn: Callable[[Generator[LeakerRecord, None, None]], tuple[int, int]],
    _depth: int = 0,
) -> tuple[int, int]:
    """
    Parse a single file and index all records it produces.

    If the file is an archive, unpack it first and recurse into each
    extracted file.  Returns (records_indexed, errors).
    """
    if _depth > MAX_ARCHIVE_DEPTH:
        logger.warning("Max archive depth reached — skipping: %s", path)
        return 0, 0

    if is_archive(path):
        # Unpack into a unique staging subdirectory named after the archive
        stage = STAGING_DIR / f"{path.stem}_{int(time.time())}"
        files = unpack_archive(path, stage)
        total_ok = total_err = 0
        for f in files:
            ok, err = process_file(f, index_fn, _depth + 1)   # recurse
            total_ok += ok
            total_err += err
        return total_ok, total_err

    logger.info("Parsing: %s", path)
    try:
        records = extract_file(str(path))
        return index_fn(records)
    except Exception as exc:
        logger.error("Extraction failed for %s: %s", path, exc)
        return 0, 1


def move_to_processed(path: Path, dropzone: Path) -> None:
    """Move a processed file to PROCESSED_DIR preserving relative structure."""
    try:
        rel = path.relative_to(dropzone)
    except ValueError:
        rel = Path(path.name)
    dest = PROCESSED_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    logger.info("Moved to processed/: %s", rel)


# ══════════════════════════════════════════════════════════════════════════════
# 3. WATCHDOG EVENT HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class DropZoneHandler(FileSystemEventHandler):
    """
    Watchdog handler that reacts to files appearing in the drop zone.

    Flow for each new file
    ----------------------
      1. Brief settle wait  (let the OS finish writing / copying)
      2. Unpack if archive
      3. extract → parse → index
      4. Move to processed/
    """

    # Paths whose names indicate internal / already-processed locations
    _IGNORE_PARTS = {"_staging", "processed", ".git", "__pycache__"}

    def __init__(
        self,
        dropzone: Path,
        index_fn: Callable[[Generator[LeakerRecord, None, None]], tuple[int, int]],
        settle_seconds: float = 2.0,
        move_after: bool = True,
    ):
        super().__init__()
        self.dropzone       = dropzone
        self.index_fn       = index_fn
        self.settle_seconds = settle_seconds
        self.move_after     = move_after
        self._lock          = Lock()
        self._seen: set[str] = set()

    # ------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        self._enqueue(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        # Also fires when another process moves a file into the drop zone
        if event.is_directory:
            return
        self._enqueue(Path(event.dest_path))

    # ------------------------------------------------------------------

    def _enqueue(self, path: Path) -> None:
        """Ignore internal paths; dispatch unique paths to a background thread."""
        if any(part in self._IGNORE_PARTS for part in path.parts):
            return
        key = str(path.resolve())
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)
        Thread(target=self._handle, args=(path, key), daemon=True).start()

    def _handle(self, path: Path, key: str) -> None:
        """Settle → process → (optionally) move."""
        time.sleep(self.settle_seconds)
        if not path.is_file():
            self._seen.discard(key)
            return

        print(f"\n  [DropZone] ↓  {path.name}")
        ok, err = process_file(path, self.index_fn)
        status  = f"[green]{ok:,} records indexed[/green]" if ok else ""
        errmsg  = f"  [red]{err} errors[/red]" if err else ""
        print(f"  [DropZone] ✓  {path.name}  →  {ok:,} indexed, {err} errors")

        if self.move_after:
            move_to_processed(path, self.dropzone)

        with self._lock:
            self._seen.discard(key)


# ══════════════════════════════════════════════════════════════════════════════
# 4. PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def start_watcher(
    index_fn: Callable[[Generator[LeakerRecord, None, None]], tuple[int, int]],
    dropzone: Path = DEFAULT_DROPZONE,
    settle_seconds: float = 2.0,
    move_after: bool = True,
    block: bool = True,
) -> Observer:
    """
    Start watching the drop zone for new files.

    Parameters
    ----------
    index_fn       : Callable(records_generator) → (ok, err).
                     Typically: lambda recs: indexer.index_records(recs)
    dropzone       : Directory to watch.  Created if missing.
    settle_seconds : Seconds to wait after file appears before processing
                     (allows large files time to finish writing).
    move_after     : If True, move processed files to processed/.
    block          : If True, block until Ctrl-C (use for CLI).
                     If False, return the Observer for caller to manage.
    """
    dropzone.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    handler  = DropZoneHandler(dropzone, index_fn,
                               settle_seconds=settle_seconds,
                               move_after=move_after)
    observer = Observer()
    observer.schedule(handler, str(dropzone), recursive=True)
    observer.start()

    print(f"")
    print(f"  Drop Zone  :  {dropzone.resolve()}")
    print(f"  Processed  :  {PROCESSED_DIR.resolve()}")
    print(f"  Supports   :  all file types + ZIP / TAR / GZ / 7z archives")
    print(f"  Press Ctrl-C to stop.\n")

    if block:
        try:
            while observer.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            print("\n  [DropZone] Stopped.")

    return observer
