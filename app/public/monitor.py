"""Operator-side probe of the public store and publication lag; never served publicly.

The public server can only see the public file, so it cannot tell a quiet source from
a stopped publisher. This probe runs locally with read access to both stores and asks
the question directly: has the publisher caught up with the source's change counters?
A healthy watcher publishes every few seconds, so a change still unpublished after the
settle window means publication is stuck.
"""

import argparse
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.dashboard.queries import table_exists
from app.public.database import open_readonly


def _source_changes(source: Path) -> list[Any] | None:
    with open_readonly(source, allow_wal=True) as conn:
        if not table_exists(conn, "publication_changes"):
            return None
        row = conn.execute(
            "SELECT source_id, details, performance, activity FROM publication_changes "
            "WHERE singleton=1"
        ).fetchone()
    return list(row) if row else None


def _published_changes(public: Path) -> list[Any] | None:
    with open_readonly(public) as conn:
        if not table_exists(conn, "publication_checkpoint"):
            return None
        row = conn.execute(
            "SELECT content FROM publication_checkpoint WHERE singleton=1"
        ).fetchone()
    if not row:
        return None
    changes = json.loads(row[0]).get("changes")
    return list(changes) if changes else None


def probe(
    source: Path,
    public: Path,
    *,
    settle_seconds: float = 30.0,
    interval: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "public_integrity": "unavailable",
        "public_wal": None,
        "publication": "unknown",
        "lag_seconds": None,
    }
    if not public.is_file():
        return result
    with public.open("rb") as header:
        result["public_wal"] = header.read(20)[18:20] == bytes([2, 2])
    try:
        conn = sqlite3.connect(f"{public.resolve().as_uri()}?mode=ro", uri=True)
        try:
            result["public_integrity"] = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return result
    if result["public_integrity"] != "ok" or result["public_wal"] or not source.is_file():
        return result
    started = monotonic()
    try:
        while True:
            wanted, published = _source_changes(source), _published_changes(public)
            waited = monotonic() - started
            if wanted is None or wanted == published:
                result["publication"] = "current"
                result["lag_seconds"] = round(waited, 1)
                return result
            if waited >= settle_seconds:
                result["publication"] = "stuck"
                result["lag_seconds"] = round(waited, 1)
                return result
            sleep(interval)
    except (sqlite3.Error, ValueError):
        result["publication"] = "unknown"
        return result


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.public.monitor")
    parser.add_argument("--source", default="data/boustrategy.db")
    parser.add_argument("--public-db", default="data/boustrategy.public.db")
    parser.add_argument("--settle", type=float, default=30.0)
    args = parser.parse_args()
    if Path(args.source).resolve() == Path(args.public_db).resolve():
        parser.error("public store must be separate from source")
    print(json.dumps(probe(Path(args.source), Path(args.public_db), settle_seconds=args.settle)))


if __name__ == "__main__":
    main()
