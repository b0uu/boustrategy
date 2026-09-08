import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_readonly(path: str | Path, *, allow_wal: bool = False) -> Iterator[sqlite3.Connection]:
    """Open an existing database without initialization or migrations."""
    resolved = Path(path).resolve()
    if resolved.exists() and not allow_wal:
        with resolved.open("rb") as header:
            wal = header.read(20)[18:20] == bytes([2, 2])
        if wal:
            raise sqlite3.OperationalError(
                "WAL source requires trusted publication before public reads"
            )
    conn = (
        sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
        if resolved.exists()
        else sqlite3.connect(":memory:")
    )
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()
