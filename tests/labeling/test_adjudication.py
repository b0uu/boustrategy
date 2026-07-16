import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.labeling.adjudication import (
    adjudicate,
    adjudication_progress,
    pending_disagreements,
)
from app.labeling.experiment import _reconfigure_stdout_utf8
from app.labeling.server import create_app
from app.storage.database import connect
from app.x.posts import XPost, insert_new_posts, mark_reviewed


def make_post(
    post_id: str,
    handle: str = "someone",
    *,
    posted_at: datetime | None = None,
    text: str = "",
) -> XPost:
    return XPost(
        post_id=post_id,
        handle=handle,
        posted_at=posted_at or datetime(2026, 7, 1, tzinfo=UTC),
        text=text or f"post {post_id}",
        url=f"https://x.com/{handle}/status/{post_id}",
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


def seed(db_path: Path, posts: list[XPost]) -> None:
    conn = connect(str(db_path))
    insert_new_posts(conn, posts)
    conn.close()


def add_prediction(conn: object, post_id: str, prediction: str, reason: str = "") -> None:
    conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, predicted_at) "
        "VALUES (?, 'gpt-5.6-luna', ?, ?, '2026-07-15T00:00:00+00:00')",
        (post_id, prediction, reason),
    )
    conn.commit()  # type: ignore[attr-defined]


PREDICTOR = "gpt-5.6-luna"


# --- pending_disagreements ---


def test_pending_disagreements_only_mismatches_fn_before_fp(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(
        db_path,
        [
            make_post("agree1", posted_at=datetime(2026, 7, 1, tzinfo=UTC)),
            make_post("fp1", posted_at=datetime(2026, 7, 2, tzinfo=UTC)),
            make_post("fn1", posted_at=datetime(2026, 7, 3, tzinfo=UTC)),
        ],
    )
    conn = connect(str(db_path))
    mark_reviewed(conn, "agree1", "significant")
    mark_reviewed(conn, "fp1", "skipped")
    mark_reviewed(conn, "fn1", "significant")
    add_prediction(conn, "agree1", "significant")
    add_prediction(conn, "fp1", "significant")
    add_prediction(conn, "fn1", "skip")

    result = pending_disagreements(conn, PREDICTOR)
    conn.close()

    assert [item["post_id"] for item in result] == ["fn1", "fp1"]


def test_pending_disagreements_excludes_already_adjudicated(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("fp1"), make_post("fp2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "fp1", "skipped")
    mark_reviewed(conn, "fp2", "skipped")
    add_prediction(conn, "fp1", "significant")
    add_prediction(conn, "fp2", "significant")

    adjudicate(conn, PREDICTOR, "fp1", "upheld")
    result = pending_disagreements(conn, PREDICTOR)
    conn.close()

    assert [item["post_id"] for item in result] == ["fp2"]


# --- adjudicate: flips ---


def test_overturned_fp_flips_skipped_to_significant(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    add_prediction(conn, "1", "significant")

    adjudicate(conn, PREDICTOR, "1", "overturned")

    (status,) = conn.execute("SELECT review_status FROM x_posts WHERE post_id = '1'").fetchone()
    (label_before,) = conn.execute(
        "SELECT label_before FROM x_adjudications WHERE post_id = '1' AND predictor = ?",
        (PREDICTOR,),
    ).fetchone()
    conn.close()

    assert status == "significant"
    assert label_before == "skipped"


def test_overturned_fn_flips_significant_to_skipped(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    add_prediction(conn, "1", "skip")

    adjudicate(conn, PREDICTOR, "1", "overturned")

    (status,) = conn.execute("SELECT review_status FROM x_posts WHERE post_id = '1'").fetchone()
    (label_before,) = conn.execute(
        "SELECT label_before FROM x_adjudications WHERE post_id = '1' AND predictor = ?",
        (PREDICTOR,),
    ).fetchone()
    conn.close()

    assert status == "skipped"
    assert label_before == "significant"


def test_upheld_and_borderline_flip_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    mark_reviewed(conn, "2", "skipped")
    add_prediction(conn, "1", "significant")
    add_prediction(conn, "2", "significant")

    adjudicate(conn, PREDICTOR, "1", "upheld")
    adjudicate(conn, PREDICTOR, "2", "borderline")

    (status1,) = conn.execute("SELECT review_status FROM x_posts WHERE post_id = '1'").fetchone()
    (status2,) = conn.execute("SELECT review_status FROM x_posts WHERE post_id = '2'").fetchone()
    conn.close()

    assert status1 == "skipped"
    assert status2 == "skipped"


def test_captured_post_records_verdict_without_flip_and_flags_manual_review(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "captured")
    add_prediction(conn, "1", "skip")

    adjudicate(conn, PREDICTOR, "1", "overturned")

    status, note = conn.execute(
        "SELECT review_status, note FROM x_adjudications a "
        "JOIN x_posts p ON p.post_id = a.post_id "
        "WHERE a.post_id = '1' AND a.predictor = ?",
        (PREDICTOR,),
    ).fetchone()
    conn.close()

    assert status == "captured"
    assert "needs_manual_review" in note


# --- re-adjudication ---


def test_reajudication_overturned_to_upheld_restores_original_label(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    add_prediction(conn, "1", "significant")

    adjudicate(conn, PREDICTOR, "1", "overturned")
    (status_after_overturn,) = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = '1'"
    ).fetchone()

    adjudicate(conn, PREDICTOR, "1", "upheld")
    (status_after_upheld,) = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = '1'"
    ).fetchone()
    label_before, verdict = conn.execute(
        "SELECT label_before, verdict FROM x_adjudications WHERE post_id = '1' AND predictor = ?",
        (PREDICTOR,),
    ).fetchone()
    conn.close()

    assert status_after_overturn == "significant"
    assert status_after_upheld == "skipped"
    assert label_before == "skipped"
    assert verdict == "upheld"


# --- snapshot ---


def test_first_adjudication_writes_original_snapshot_exactly_once(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    mark_reviewed(conn, "2", "significant")
    add_prediction(conn, "1", "significant")
    add_prediction(conn, "2", "skip")

    adjudicate(conn, PREDICTOR, "1", "upheld")
    adjudicate(conn, PREDICTOR, "2", "upheld")

    rows = conn.execute(
        "SELECT metrics_json FROM x_score_snapshots WHERE predictor = ? AND label = 'original'",
        (PREDICTOR,),
    ).fetchall()
    conn.close()

    assert len(rows) == 1


# --- progress / metrics comparison ---


def test_progress_live_metrics_improve_after_overturn(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    # post 1 agrees; post 2 disagrees (human error: skipped, model says significant)
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    add_prediction(conn, "1", "significant")
    add_prediction(conn, "2", "significant")

    result = adjudicate(conn, PREDICTOR, "2", "overturned")
    progress = adjudication_progress(conn, PREDICTOR)
    conn.close()

    assert progress["original_metrics"]["agreement_pct"] == pytest.approx(50.0)
    assert progress["live_metrics"]["agreement_pct"] == pytest.approx(100.0)
    assert result["live_metrics"]["agreement_pct"] == pytest.approx(100.0)


def test_progress_excludes_borderline_from_second_metrics_view(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    add_prediction(conn, "1", "significant")
    add_prediction(conn, "2", "significant")

    adjudicate(conn, PREDICTOR, "2", "borderline")
    progress = adjudication_progress(conn, PREDICTOR)
    conn.close()

    assert progress["live_metrics"]["total"] == 2
    assert progress["live_metrics_excluding_borderline"]["total"] == 1


# --- UI ---


def test_adjudicate_page_renders_comparison_strip(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    add_prediction(conn, "1", "significant", "looks substantive")
    conn.close()

    client = TestClient(create_app(db_path))
    response = client.get("/adjudicate", params={"predictor": PREDICTOR})

    assert response.status_code == 200
    assert "comparison-table" in response.text
    assert "looks substantive" in response.text


def test_post_adjudicate_advances_and_returns_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "labeling.db"
    seed(
        db_path,
        [
            make_post("1", posted_at=datetime(2026, 7, 1, tzinfo=UTC)),
            make_post("2", posted_at=datetime(2026, 7, 2, tzinfo=UTC)),
        ],
    )
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    add_prediction(conn, "1", "skip")
    add_prediction(conn, "2", "significant")
    conn.close()

    client = TestClient(create_app(db_path))
    response = client.post(
        "/api/adjudicate",
        json={"predictor": PREDICTOR, "post_id": "1", "verdict": "upheld"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["empty"] is False
    assert body["next"]["post_id"] == "2"
    assert "live_metrics" in body


def test_post_adjudicate_invalid_verdict_returns_422_and_changes_nothing(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "labeling.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    add_prediction(conn, "1", "significant")
    conn.close()

    client = TestClient(create_app(db_path))
    response = client.post(
        "/api/adjudicate",
        json={"predictor": PREDICTOR, "post_id": "1", "verdict": "not_a_verdict"},
    )

    assert response.status_code == 422

    conn = connect(str(db_path))
    (status,) = conn.execute("SELECT review_status FROM x_posts WHERE post_id = '1'").fetchone()
    (adjudication_count,) = conn.execute(
        "SELECT COUNT(*) FROM x_adjudications WHERE post_id = '1'"
    ).fetchone()
    conn.close()

    assert status == "skipped"
    assert adjudication_count == 0


# --- stdout utf-8 fix ---


def test_reconfigure_stdout_utf8_is_a_noop_when_stream_lacks_reconfigure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # BytesIO has no reconfigure(); this must not raise.
    monkeypatch.setattr("sys.stdout", io.StringIO())
    _reconfigure_stdout_utf8()


def test_reconfigure_stdout_utf8_sets_encoding_and_survives_non_cp1252_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _reconfigure_stdout_utf8()
    # Would raise UnicodeEncodeError on a cp1252 stdout without the fix.
    print("non-cp1252 text: — ‘curly’ \U0001f600")
    captured = capsys.readouterr()
    assert "—" in captured.out
