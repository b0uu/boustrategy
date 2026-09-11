import sqlite3
from pathlib import Path

from app.public.monitor import probe
from app.public.publication import publish
from app.storage.database import connect
from tests.public.test_public_v2 import seed


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def change_source(source: Path) -> None:
    conn = connect(source)
    conn.execute(
        "UPDATE decision_records SET record_json=json_set(record_json, "
        "'$.public_summary', 'Changed after publication')"
    )
    conn.commit()
    conn.close()


def test_probe_reports_a_current_store_without_writing(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=2)
    publish(source, public)
    before = public.read_bytes()

    result = probe(source, public, settle_seconds=0)

    assert result == {
        "public_integrity": "ok",
        "public_wal": False,
        "publication": "current",
        "lag_seconds": 0.0,
    }
    assert public.read_bytes() == before
    assert not Path(f"{public}-journal").exists() and not Path(f"{public}-wal").exists()


def test_probe_waits_for_the_watcher_then_reports_stuck(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=2)
    publish(source, public)
    change_source(source)
    clock = Clock()

    def idle(seconds: float) -> None:
        clock.now += seconds

    stuck = probe(source, public, settle_seconds=30, sleep=idle, monotonic=clock)

    assert (stuck["publication"], stuck["lag_seconds"]) == ("stuck", 30.0)

    clock.now = 0.0

    def watcher_catches_up(seconds: float) -> None:
        clock.now += seconds
        publish(source, public)

    caught_up = probe(source, public, settle_seconds=30, sleep=watcher_catches_up, monotonic=clock)

    assert (caught_up["publication"], caught_up["lag_seconds"]) == ("current", 5.0)


def test_probe_flags_corrupt_missing_and_wal_public_stores(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    seed(source, count=1)

    assert probe(source, public)["public_integrity"] == "unavailable"

    publish(source, public)
    conn = sqlite3.connect(public)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    wal = probe(source, public, settle_seconds=0)
    assert wal["public_wal"] is True
    assert wal["publication"] == "unknown"

    public.unlink()
    for sidecar in (Path(f"{public}-wal"), Path(f"{public}-shm")):
        sidecar.unlink(missing_ok=True)
    public.write_bytes(b"corrupt " * 512)
    corrupt = probe(source, public, settle_seconds=0)
    assert corrupt["public_integrity"] != "ok"
    assert corrupt["publication"] == "unknown"
