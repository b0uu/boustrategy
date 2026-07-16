import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.labeling.experiment import (
    export_batches,
    ingest_predictions,
    score_predictor,
)
from app.storage.database import connect
from app.x.posts import MediaItem, XPost, insert_new_posts, mark_reviewed


def make_post(
    post_id: str,
    handle: str = "someone",
    *,
    text: str = "",
    media: list[MediaItem] | None = None,
) -> XPost:
    return XPost(
        post_id=post_id,
        handle=handle,
        posted_at=datetime(2026, 7, 1, tzinfo=UTC),
        text=text or f"post {post_id}",
        url=f"https://x.com/{handle}/status/{post_id}",
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
        reply_context="in reply to something",
        media=media or [],
    )


def seed(db_path: Path, posts: list[XPost]) -> None:
    conn = connect(str(db_path))
    insert_new_posts(conn, posts)
    conn.close()


# --- export ---


def test_export_excludes_unreviewed_posts(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    conn.close()

    conn = connect(str(db_path))
    batch_count, post_count = export_batches(conn, tmp_path / "export")
    conn.close()

    assert batch_count == 1
    assert post_count == 1
    lines = (tmp_path / "export" / "batch_001.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["post_id"] == "1"


def test_export_never_contains_review_status(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    mark_reviewed(conn, "2", "significant")
    conn.close()

    conn = connect(str(db_path))
    export_batches(conn, tmp_path / "export")
    conn.close()

    for path in (tmp_path / "export").glob("*.jsonl"):
        content = path.read_text(encoding="utf-8")
        assert "review_status" not in content

    # Sanity: every exported line has exactly the blind field set, no more.
    lines = (tmp_path / "export" / "batch_001.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        record = json.loads(line)
        assert set(record.keys()) == {
            "post_id",
            "handle",
            "posted_at",
            "text",
            "reply_context",
            "media",
            "url",
        }


def test_export_writes_rubric(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "skipped")
    conn.close()

    conn = connect(str(db_path))
    export_batches(conn, tmp_path / "export")
    conn.close()

    rubric = (tmp_path / "export" / "RUBRIC.md").read_text(encoding="utf-8")
    assert "significant" in rubric
    assert "review_status" not in rubric


def test_export_splits_into_batches(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    posts = [make_post(str(i)) for i in range(5)]
    seed(db_path, posts)
    conn = connect(str(db_path))
    for i in range(5):
        mark_reviewed(conn, str(i), "skipped")
    conn.close()

    conn = connect(str(db_path))
    batch_count, post_count = export_batches(conn, tmp_path / "export", batch_size=2)
    conn.close()

    assert batch_count == 3
    assert post_count == 5
    assert (tmp_path / "export" / "batch_001.jsonl").exists()
    assert (tmp_path / "export" / "batch_002.jsonl").exists()
    assert (tmp_path / "export" / "batch_003.jsonl").exists()
    batch1_lines = (
        (tmp_path / "export" / "batch_001.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert len(batch1_lines) == 2


def test_export_includes_media(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(
        db_path,
        [make_post("1", media=[MediaItem(url="https://x.com/m1.jpg", media_type="photo")])],
    )
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    conn.close()

    conn = connect(str(db_path))
    export_batches(conn, tmp_path / "export")
    conn.close()

    lines = (tmp_path / "export" / "batch_001.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["media"] == [
        {"url": "https://x.com/m1.jpg", "media_type": "photo", "alt_text": ""}
    ]


# --- ingest ---


def test_ingest_inserts_predictions(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])

    pred_file = tmp_path / "preds.jsonl"
    pred_file.write_text(
        "\n".join(
            [
                json.dumps({"post_id": "1", "prediction": "significant", "reason": "claim"}),
                json.dumps({"post_id": "2", "prediction": "skip", "reason": "no claim"}),
            ]
        ),
        encoding="utf-8",
    )

    conn = connect(str(db_path))
    ingested = ingest_predictions(conn, "test-model", pred_file)

    rows = conn.execute(
        "SELECT post_id, prediction, reason FROM x_gate_predictions ORDER BY post_id"
    ).fetchall()
    conn.close()

    assert ingested == 2
    assert rows == [
        ("1", "significant", "claim"),
        ("2", "skip", "no claim"),
    ]


def test_ingest_rejects_invalid_prediction_value(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])

    pred_file = tmp_path / "preds.jsonl"
    pred_file.write_text(json.dumps({"post_id": "1", "prediction": "maybe"}), encoding="utf-8")

    conn = connect(str(db_path))
    with pytest.raises(ValueError, match="invalid prediction"):
        ingest_predictions(conn, "test-model", pred_file)
    conn.close()


def test_ingest_rejects_unknown_post_id(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])

    pred_file = tmp_path / "preds.jsonl"
    pred_file.write_text(json.dumps({"post_id": "999", "prediction": "skip"}), encoding="utf-8")

    conn = connect(str(db_path))
    with pytest.raises(ValueError, match="unknown post_id"):
        ingest_predictions(conn, "test-model", pred_file)
    conn.close()


def test_ingest_replaces_on_reingest(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])

    pred_file = tmp_path / "preds.jsonl"
    pred_file.write_text(
        json.dumps({"post_id": "1", "prediction": "significant"}), encoding="utf-8"
    )
    conn = connect(str(db_path))
    ingest_predictions(conn, "test-model", pred_file)

    pred_file.write_text(json.dumps({"post_id": "1", "prediction": "skip"}), encoding="utf-8")
    ingest_predictions(conn, "test-model", pred_file)

    rows = conn.execute(
        "SELECT post_id, prediction FROM x_gate_predictions WHERE predictor = ?",
        ("test-model",),
    ).fetchall()
    conn.close()

    assert rows == [("1", "skip")]


def test_ingest_reads_directory_of_batches(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2")])

    batch_dir = tmp_path / "preds"
    batch_dir.mkdir()
    (batch_dir / "batch_001.jsonl").write_text(
        json.dumps({"post_id": "1", "prediction": "significant"}), encoding="utf-8"
    )
    (batch_dir / "batch_002.jsonl").write_text(
        json.dumps({"post_id": "2", "prediction": "skip"}), encoding="utf-8"
    )

    conn = connect(str(db_path))
    ingested = ingest_predictions(conn, "test-model", batch_dir)
    conn.close()

    assert ingested == 2


# --- score ---


def test_score_confusion_matrix_and_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(
        db_path,
        [
            make_post("1", handle="alice", text="tp post"),
            make_post("2", handle="alice", text="fp post"),
            make_post("3", handle="bob", text="tn post"),
            make_post("4", handle="bob", text="fn post"),
        ],
    )
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    mark_reviewed(conn, "3", "skipped")
    mark_reviewed(conn, "4", "significant")

    predictions = [
        ("1", "significant"),  # TP
        ("2", "significant"),  # FP
        ("3", "skip"),  # TN
        ("4", "skip"),  # FN
    ]
    for post_id, prediction in predictions:
        conn.execute(
            "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
            "predicted_at) VALUES (?, 'test-model', ?, '', '2026-07-15T00:00:00+00:00')",
            (post_id, prediction),
        )
    conn.commit()

    report = score_predictor(conn, "test-model")
    conn.close()

    assert report["tp"] == 1
    assert report["fp"] == 1
    assert report["tn"] == 1
    assert report["fn"] == 1
    assert report["total"] == 4
    assert report["agreement_pct"] == pytest.approx(50.0)
    assert report["precision"] == pytest.approx(0.5)
    assert report["recall"] == pytest.approx(0.5)
    assert "alice" in report["per_handle"]
    assert "bob" in report["per_handle"]
    assert report["per_handle"]["alice"]["total"] == 2
    assert report["per_handle"]["bob"]["total"] == 2


def test_score_captured_counts_as_positive_label(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "captured")
    conn.execute(
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
        "predicted_at) VALUES ('1', 'test-model', 'significant', '', "
        "'2026-07-15T00:00:00+00:00')"
    )
    conn.commit()

    report = score_predictor(conn, "test-model")
    conn.close()

    assert report["tp"] == 1


def test_score_counts_labels_without_predictions_and_vice_versa(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(db_path, [make_post("1"), make_post("2"), make_post("3")])
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    # post 3 stays unreviewed but still gets a prediction ingested.
    conn.execute(
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
        "predicted_at) VALUES ('1', 'test-model', 'significant', '', "
        "'2026-07-15T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
        "predicted_at) VALUES ('3', 'test-model', 'skip', '', "
        "'2026-07-15T00:00:00+00:00')"
    )
    conn.commit()

    report = score_predictor(conn, "test-model")
    conn.close()

    assert report["labels_without_prediction"] == 1  # post 2 has label, no prediction
    assert report["predictions_without_label"] == 1  # post 3 has prediction, no label


def test_score_per_modality_split(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    seed(
        db_path,
        [
            make_post("1", media=[MediaItem(url="https://x.com/m.jpg", media_type="photo")]),
            make_post("2"),
        ],
    )
    conn = connect(str(db_path))
    mark_reviewed(conn, "1", "significant")
    mark_reviewed(conn, "2", "skipped")
    conn.execute(
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
        "predicted_at) VALUES ('1', 'test-model', 'significant', '', "
        "'2026-07-15T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO x_gate_predictions (post_id, predictor, prediction, reason, "
        "predicted_at) VALUES ('2', 'test-model', 'skip', '', "
        "'2026-07-15T00:00:00+00:00')"
    )
    conn.commit()

    report = score_predictor(conn, "test-model")
    conn.close()

    assert report["per_modality"]["media"]["total"] == 1
    assert report["per_modality"]["text_only"]["total"] == 1
