import json
import sqlite3
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.storage.database import connect
from app.x.accounts import Account, upsert_account
from app.x.client import FetchResult
from app.x.pipeline import cycle, render_digest, render_weekly, route_predictions, store_note
from app.x.posts import MediaItem, XPost, insert_new_posts, record_post_reads
from app.x.run import _cmd_fetch


def _post(
    post_id: str,
    text: str,
    *,
    handle: str = "analyst",
    fetched_at: datetime | None = None,
    media: list[MediaItem] | None = None,
) -> XPost:
    now = fetched_at or datetime.now(UTC)
    return XPost(
        post_id=post_id,
        handle=handle,
        posted_at=now,
        text=text,
        url=f"https://x.com/{handle}/status/{post_id}",
        fetched_at=now,
        media=media or [],
    )


def _run(conn: sqlite3.Connection, run_id: str, status: str = "exported") -> None:
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, finished_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run_id.rsplit("-", 1)[1],
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
            status,
        ),
    )
    conn.commit()


def _prediction_file(path: Path, records: list[dict[str, str]]) -> Path:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def test_database_creates_pipeline_tables(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'x_%'"
        )
    }

    assert {"x_runs", "x_route_decisions", "x_article_queue", "x_digest_notes"} <= names


def test_cycle_calendar_no_op_creates_no_run(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    cycle(conn, "morning", date(2026, 7, 18), tmp_path / "out", lambda _: None)

    assert conn.execute("SELECT COUNT(*) FROM x_runs").fetchone()[0] == 0


def test_weekly_cycle_creates_completed_anchor_and_repeats_as_no_op(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    cycle(conn, "weekly", date(2026, 7, 19), tmp_path / "out", lambda _: None)
    cycle(conn, "weekly", date(2026, 7, 19), tmp_path / "out", lambda _: None)

    assert conn.execute("SELECT status FROM x_runs").fetchone()[0] == "routed"


def test_cycle_crashes_for_stuck_run(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _run(conn, "2026-07-20-morning", "failed")

    with pytest.raises(RuntimeError, match="stuck"):
        cycle(conn, "morning", date(2026, 7, 20), tmp_path / "out", lambda _: None)


def test_cycle_records_fetch_failure(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    def fail(_: sqlite3.Connection) -> None:
        raise ConnectionError("synthetic fetch failure")

    with pytest.raises(ConnectionError, match="synthetic fetch failure"):
        cycle(conn, "morning", date(2026, 7, 20), tmp_path / "out", fail)

    assert conn.execute("SELECT status FROM x_runs").fetchone()[0] == "failed"


def test_fetch_uses_all_active_accounts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    upsert_account(conn, Account(handle="core", user_id="1", tier="core"))
    upsert_account(conn, Account(handle="scan", user_id="2", tier="scan"))
    handles: list[str] = []

    def fetch(user_id: str, handle: str, since_id: str | None) -> FetchResult:
        handles.append(handle)
        return FetchResult([], 0)

    _cmd_fetch(conn, resolve_ids=lambda _: {}, fetch_posts=fetch)

    assert handles == ["core", "scan"]


def test_cycle_auto_routes_only_link_only_posts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    def fetch(target: sqlite3.Connection) -> None:
        insert_new_posts(
            target,
            [
                _post("1", "New report https://example.com/a"),
                _post(
                    "2",
                    "https://example.com/media",
                    media=[MediaItem(url="https://example.com/image.jpg", media_type="photo")],
                ),
                _post(
                    "3",
                    "This sentence contains substantially more than forty characters after its link https://example.com/b",
                ),
            ],
        )
        record_post_reads(target, 3)

    cycle(conn, "morning", date(2026, 7, 20), tmp_path / "out", fetch)

    routes = conn.execute(
        "SELECT post_id, route, predictor FROM x_route_decisions ORDER BY post_id"
    ).fetchall()
    assert routes == [("1", "article_queue", "code:link_only")]
    assert conn.execute("SELECT post_id FROM x_article_queue").fetchall() == [("1",)]
    assert conn.execute(
        "SELECT posts_fetched, posts_exported, reads_used, status FROM x_runs"
    ).fetchone() == (3, 2, 3, "exported")


def test_cycle_export_excludes_pre_cutoff_unreviewed_post(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    cutoff = datetime.now(UTC) - timedelta(hours=2)
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, finished_at, status)
        VALUES ('2026-07-19-close', 'close', ?, ?, 'routed')
        """,
        (cutoff.isoformat(), (cutoff + timedelta(minutes=1)).isoformat()),
    )
    insert_new_posts(
        conn, [_post("old", "old substantive post", fetched_at=cutoff - timedelta(seconds=1))]
    )

    out = tmp_path / "out"
    cycle(conn, "morning", date(2026, 7, 20), out, lambda _: None)

    assert list(out.glob("batch_*.jsonl")) == []
    assert (
        conn.execute(
            "SELECT posts_exported FROM x_runs WHERE run_id = '2026-07-20-morning'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    ("prediction", "rank"),
    [
        ("significant", ""),
        ("significant", "urgent"),
        ("skip", "headline"),
        ("unsupported", ""),
    ],
)
def test_route_rejects_bad_rank_combinations(tmp_path: Path, prediction: str, rank: str) -> None:
    conn = connect(tmp_path / "synthetic.db")
    insert_new_posts(conn, [_post("1", "claim")])
    _run(conn, "2026-07-20-morning")
    source = _prediction_file(
        tmp_path / "predictions.jsonl",
        [{"post_id": "1", "prediction": prediction, "rank": rank}],
    )

    with pytest.raises(ValueError):
        route_predictions(conn, "2026-07-20-morning", "judge", source)


def test_route_rejects_unknown_post(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    _run(conn, "2026-07-20-morning")
    source = _prediction_file(
        tmp_path / "predictions.jsonl", [{"post_id": "missing", "prediction": "skip"}]
    )

    with pytest.raises(ValueError, match="unknown post_id"):
        route_predictions(conn, "2026-07-20-morning", "judge", source)


def test_route_rejects_cross_run_and_same_run_replaces_without_touching_label(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "synthetic.db")
    insert_new_posts(conn, [_post("1", "claim")])
    _run(conn, "2026-07-20-morning")
    _run(conn, "2026-07-20-midday")
    first = _prediction_file(
        tmp_path / "first.jsonl",
        [{"post_id": "1", "prediction": "significant", "rank": "notable"}],
    )
    replacement = _prediction_file(
        tmp_path / "replacement.jsonl", [{"post_id": "1", "prediction": "skip"}]
    )

    route_predictions(conn, "2026-07-20-morning", "judge-1", first)
    route_predictions(conn, "2026-07-20-morning", "judge-2", replacement)
    assert conn.execute(
        "SELECT route, rank, predictor FROM x_route_decisions WHERE post_id = '1'"
    ).fetchone() == ("skip", "", "judge-2")
    assert (
        conn.execute("SELECT review_status FROM x_posts WHERE post_id = '1'").fetchone()[0]
        == "unreviewed"
    )

    with pytest.raises(ValueError, match="already routed"):
        route_predictions(conn, "2026-07-20-midday", "judge-3", first)


def test_notes_and_renderers_are_deterministic_and_carry_pending_articles(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "synthetic.db")
    upsert_account(conn, Account(handle="analyst", user_id="1"))
    insert_new_posts(conn, [_post("1", "headline claim"), _post("2", "linked article")])
    _run(conn, "2026-07-20-morning", "routed")
    conn.execute(
        """
        INSERT INTO x_route_decisions
            (post_id, run_id, route, rank, reason, predictor, decided_at)
        VALUES ('1', '2026-07-20-morning', 'digest', 'headline', 'new evidence', 'judge', ?),
               ('2', '2026-07-20-morning', 'article_queue', '', '', 'code:link_only', ?)
        """,
        (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
    )
    conn.execute(
        "INSERT INTO x_article_queue (post_id, queued_at) VALUES ('2', ?)",
        ((datetime.now(UTC) - timedelta(days=1)).isoformat(),),
    )
    conn.commit()
    store_note(conn, date(2026, 7, 20), "morning", "judge", "first")
    store_note(conn, date(2026, 7, 20), "morning", "judge", "refined synthesis")
    store_note(conn, date(2026, 7, 20), "weekly", "weekly-judge", "weekly synthesis")

    daily_path = tmp_path / "daily.md"
    first = render_digest(conn, date(2026, 7, 20), daily_path)
    second = render_digest(conn, date(2026, 7, 20), daily_path)
    weekly = render_weekly(conn, date(2026, 7, 20), tmp_path / "weekly.md")

    assert first == second
    assert first.startswith("# X digest: 2026-07-20 ACTIONABLE\n")
    assert "## Actionable ACTIONABLE" not in first
    assert all(
        section in first
        for section in (
            "## Actionable",
            "## Notable",
            "## Context",
            "## Article queue",
            "## Synthesis",
            "## Ops",
        )
    )
    assert "refined synthesis" in first and "first" not in first
    assert "https://x.com/analyst/status/2" in first
    assert all(
        section in weekly
        for section in (
            "## Headlines",
            "## Per-account counts",
            "## Article queue",
            "## Synthesis",
            "## Ops",
        )
    )
    assert "weekly synthesis" in weekly


def test_digest_has_no_actionable_marker_without_headlines(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")

    text = render_digest(conn, date(2026, 7, 20), tmp_path / "digest.md")

    assert text.startswith("# X digest: 2026-07-20\n")
    assert "ACTIONABLE" not in text
    assert "## Calendar" not in text


def test_digest_renders_calendar_events_in_next_seven_days(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    conn.executemany(
        """
        INSERT INTO calendar_events
            (event_type, ticker, event_date, label, source, fetched_at)
        VALUES ('earnings', 'NVDA', ?, 'estimated', 'test', '2026-01-01')
        """,
        [("2026-07-20",), ("2026-07-26",), ("2026-07-27",)],
    )

    text = render_digest(conn, date(2026, 7, 20), tmp_path / "digest.md")

    assert "## Calendar" in text
    assert "2026-07-20 | earnings | NVDA | estimated" in text
    assert "2026-07-26 | earnings | NVDA | estimated" in text
    assert "2026-07-27" not in text


def test_default_digest_path_is_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "data/digests/x.md"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
