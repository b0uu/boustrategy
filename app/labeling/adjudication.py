"""Adjudication logic: resolve human-vs-model disagreements, correct labels.

Maintainer decision (2026-07-15, see plans/016): no ongoing manual
labeling. Instead, every disagreement between a human review_status and a
model prediction is reviewed exactly once here, with three verdicts:

- upheld: the human label stands, nothing changes.
- overturned: the model was right; the stored label is corrected. This is
  the ONLY path that ever flips x_posts.review_status, and only between
  'significant' and 'skipped' — 'captured' posts carry rich signals and
  are never auto-flipped; their verdict is recorded with a
  'needs_manual_review' note instead.
- borderline: the verdict is recorded, nothing flips; scoring reports
  agreement both including and excluding borderline-adjudicated posts.

Every adjudication is an append-only row keyed by (post_id, predictor):
re-adjudicating a post first restores label_before (undoing any prior
flip) before applying the new verdict's effect, so repeated flip-flopping
never drifts from the original label.

Deliberately NOT app.x.posts.mark_reviewed: that function only allows
transitions FROM 'unreviewed', which is wrong here — adjudication flips
an already-reviewed post between 'significant' and 'skipped'.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.labeling.experiment import _human_label, score_predictor
from app.x.posts import _media_from_row

VERDICTS = ("upheld", "overturned", "borderline")


def _flip_label(conn: sqlite3.Connection, post_id: str, new_status: str) -> None:
    """The one and only place x_posts.review_status changes for adjudication.

    Unlike mark_reviewed, this has no 'FROM unreviewed' guard — it flips an
    already-reviewed post between 'significant' and 'skipped'.
    """
    conn.execute(
        "UPDATE x_posts SET review_status = ? WHERE post_id = ?",
        (new_status, post_id),
    )


def pending_disagreements(conn: sqlite3.Connection, predictor: str) -> list[dict[str, Any]]:
    """Disagreements with no adjudication row yet, FN-first then FP.

    Within each kind, oldest posted_at first (the query already orders by
    posted_at, and that order is preserved when the rows are split into
    the fn/fp buckets below).
    """
    rows = conn.execute(
        """
        SELECT p.post_id, p.handle, p.posted_at, p.text, p.url, p.reply_context,
               p.media_json, p.review_status, g.prediction, g.reason
        FROM x_posts p
        JOIN x_gate_predictions g ON g.post_id = p.post_id AND g.predictor = ?
        LEFT JOIN x_adjudications a ON a.post_id = p.post_id AND a.predictor = ?
        WHERE a.post_id IS NULL
        ORDER BY p.posted_at ASC
        """,
        (predictor, predictor),
    ).fetchall()

    fns: list[dict[str, Any]] = []
    fps: list[dict[str, Any]] = []
    for (
        post_id,
        handle,
        posted_at,
        text,
        url,
        reply_context,
        media_json,
        review_status,
        prediction,
        reason,
    ) in rows:
        human = _human_label(review_status)
        if human is None or human == prediction:
            continue
        item = {
            "post_id": post_id,
            "handle": handle,
            "posted_at": posted_at,
            "text": text,
            "url": url,
            "reply_context": reply_context,
            "media": [m.model_dump() for m in _media_from_row(media_json)],
            "human_label": human,
            "review_status": review_status,
            "captured": review_status == "captured",
            "prediction": prediction,
            "reason": reason,
        }
        if human == "significant":
            fns.append(item)
        else:
            fps.append(item)
    return fns + fps


def adjudication_progress(conn: sqlite3.Connection, predictor: str) -> dict[str, Any]:
    """Progress + metrics comparison for the adjudication header."""
    adjudicated_rows = conn.execute(
        "SELECT verdict, post_id FROM x_adjudications WHERE predictor = ?",
        (predictor,),
    ).fetchall()
    verdict_counts = {"upheld": 0, "overturned": 0, "borderline": 0}
    borderline_post_ids: set[str] = set()
    for verdict, post_id in adjudicated_rows:
        verdict_counts[verdict] += 1
        if verdict == "borderline":
            borderline_post_ids.add(post_id)

    pending = pending_disagreements(conn, predictor)
    total_disagreements = len(pending) + len(adjudicated_rows)

    snapshot_row = conn.execute(
        "SELECT metrics_json FROM x_score_snapshots WHERE predictor = ? AND label = 'original'",
        (predictor,),
    ).fetchone()
    original_metrics = json.loads(snapshot_row[0]) if snapshot_row is not None else None

    live_metrics = score_predictor(conn, predictor)
    live_metrics_excluding_borderline = score_predictor(
        conn, predictor, exclude_post_ids=frozenset(borderline_post_ids)
    )

    return {
        "predictor": predictor,
        "total_disagreements": total_disagreements,
        "adjudicated_count": len(adjudicated_rows),
        "verdict_counts": verdict_counts,
        "original_metrics": original_metrics,
        "live_metrics": live_metrics,
        "live_metrics_excluding_borderline": live_metrics_excluding_borderline,
    }


def next_payload(conn: sqlite3.Connection, predictor: str) -> dict[str, Any]:
    """The shape both the page and every adjudication API response share."""
    pending = pending_disagreements(conn, predictor)
    next_item = pending[0] if pending else None
    progress = adjudication_progress(conn, predictor)
    return {"empty": next_item is None, "next": next_item, **progress}


def adjudicate(
    conn: sqlite3.Connection, predictor: str, post_id: str, verdict: str, note: str = ""
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict {verdict!r}")

    post_row = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = ?", (post_id,)
    ).fetchone()
    if post_row is None:
        raise ValueError(f"post {post_id} not found")
    current_status = post_row[0]

    pred_row = conn.execute(
        "SELECT prediction FROM x_gate_predictions WHERE post_id = ? AND predictor = ?",
        (post_id, predictor),
    ).fetchone()
    if pred_row is None:
        raise ValueError(f"no prediction for post {post_id} by predictor {predictor!r}")
    prediction = pred_row[0]

    # Snapshot original metrics exactly once per predictor, before this (or
    # any prior) verdict has touched a label — INSERT only if absent.
    has_snapshot = conn.execute(
        "SELECT 1 FROM x_score_snapshots WHERE predictor = ? AND label = 'original'",
        (predictor,),
    ).fetchone()
    if has_snapshot is None:
        original_metrics = score_predictor(conn, predictor)
        conn.execute(
            """
            INSERT INTO x_score_snapshots (predictor, label, metrics_json, created_at)
            VALUES (?, 'original', ?, ?)
            """,
            (predictor, json.dumps(original_metrics), datetime.now(UTC).isoformat()),
        )

    existing = conn.execute(
        "SELECT label_before FROM x_adjudications WHERE post_id = ? AND predictor = ?",
        (post_id, predictor),
    ).fetchone()
    if existing is not None:
        # Re-adjudication: restore the ORIGINAL label_before before applying
        # the new verdict, so overturned -> upheld exactly undoes the flip
        # regardless of how many times this post has been re-adjudicated.
        label_before = existing[0]
        _flip_label(conn, post_id, label_before)
        current_status = label_before
    else:
        label_before = current_status

    note_final = note
    if current_status == "captured":
        # Never auto-flip a captured post; flag it for the maintainer
        # instead, regardless of which verdict was chosen.
        note_final = (note + " " if note else "") + "needs_manual_review"
    elif verdict == "overturned":
        target_status = "significant" if prediction == "significant" else "skipped"
        _flip_label(conn, post_id, target_status)
    # upheld / borderline on a non-captured post: no flip.

    conn.execute(
        """
        INSERT OR REPLACE INTO x_adjudications
            (post_id, predictor, verdict, label_before, note, adjudicated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (post_id, predictor, verdict, label_before, note_final, datetime.now(UTC).isoformat()),
    )
    conn.commit()

    return next_payload(conn, predictor)
