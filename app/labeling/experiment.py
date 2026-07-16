"""Gate-agreement experiment harness: export, ingest, score.

File-based by design (maintainer decision 2026-07-15): no LLM client, no
network call anywhere in this module. Unlabeled posts are exported to
JSONL, judged out-of-process by an external agent session, and the
resulting prediction files are ingested and scored against human labels
already sitting in x_posts.review_status.

Blind-labeling discipline (hard rule): export files must never contain
review_status or anything derived from it. Scoring is the only place
predictions and human labels are joined.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage.database import connect

RUBRIC_MD = """# Gate rubric v0 (from the maintainer's trial-week labeling bar)

Label each post `significant` or `skip`. Judge ONLY from the post content
provided (text, reply context, media). You may open media URLs to view
images. Never guess a label from the account name alone, though the
account's domain may inform how you read technical claims.

significant = the post contains a substantive claim that could, even two
steps removed, change how an AI/tech/markets theme is scored, seed or kill
an investment thesis, or shift a regime input. This includes model/
capability advancements, research results, supply-chain facts, capex and
demand signals, credible skepticism, and market-structure observations.
Tickers and direct financial content are NOT required.

skip = no articulable claim: vibes, hype without substance, pure jokes or
engagement bait, personal chatter, congratulation/reply noise, content
whose only substance sits behind an unfetched link you cannot evaluate.

When torn, skip. Output one JSON line per post:
{"post_id": "...", "prediction": "significant" | "skip", "reason": "<=15 words"}
"""

PREDICTION_VALUES = ("significant", "skip")


def export_batches(conn: Any, out_dir: str | Path, batch_size: int = 50) -> tuple[int, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = conn.execute(
        """
        SELECT post_id, handle, posted_at, text, reply_context, media_json, url
        FROM x_posts
        WHERE review_status != 'unreviewed'
        ORDER BY post_id ASC
        """
    ).fetchall()

    batch_count = 0
    post_count = 0
    for i in range(0, len(rows), batch_size):
        batch_count += 1
        chunk = rows[i : i + batch_size]
        batch_path = out / f"batch_{batch_count:03d}.jsonl"
        lines = []
        for row in chunk:
            post_id, handle, posted_at, text, reply_context, media_json, url = row
            media = [
                {
                    "url": item["url"],
                    "media_type": item["media_type"],
                    "alt_text": item.get("alt_text", ""),
                }
                for item in json.loads(media_json)
            ]
            record = {
                "post_id": post_id,
                "handle": handle,
                "posted_at": posted_at,
                "text": text,
                "reply_context": reply_context,
                "media": media,
                "url": url,
            }
            lines.append(json.dumps(record))
            post_count += 1
        batch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (out / "RUBRIC.md").write_text(RUBRIC_MD, encoding="utf-8")
    return batch_count, post_count


def ingest_predictions(conn: Any, predictor: str, in_path: str | Path) -> int:
    path = Path(in_path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]

    predicted_at = datetime.now(UTC).isoformat()
    ingested = 0
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            post_id = record["post_id"]
            prediction = record["prediction"]
            reason = record.get("reason", "")
            if prediction not in PREDICTION_VALUES:
                raise ValueError(f"invalid prediction {prediction!r} for post {post_id}")

            exists = conn.execute("SELECT 1 FROM x_posts WHERE post_id = ?", (post_id,)).fetchone()
            if exists is None:
                raise ValueError(f"unknown post_id {post_id!r} not present in x_posts")

            conn.execute(
                """
                INSERT OR REPLACE INTO x_gate_predictions
                    (post_id, predictor, prediction, reason, predicted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (post_id, predictor, prediction, reason, predicted_at),
            )
            ingested += 1
    conn.commit()
    return ingested


def _human_label(review_status: str) -> str | None:
    if review_status in ("significant", "captured"):
        return "significant"
    if review_status == "skipped":
        return "skip"
    return None


def score_predictor(
    conn: Any, predictor: str, *, exclude_post_ids: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Score a predictor against human labels.

    exclude_post_ids lets a caller (the adjudication UI) recompute agreement
    with borderline-adjudicated posts left out, without a second bespoke
    implementation — same confusion-matrix logic, just skipping some rows.
    """
    pred_rows = conn.execute(
        "SELECT post_id, prediction FROM x_gate_predictions WHERE predictor = ?",
        (predictor,),
    ).fetchall()
    predictions = {row[0]: row[1] for row in pred_rows}

    post_rows = conn.execute(
        "SELECT post_id, handle, text, review_status, media_json FROM x_posts"
    ).fetchall()

    tp = fp = tn = fn = 0
    disagreements: list[dict[str, Any]] = []
    per_handle: dict[str, dict[str, int]] = {}
    per_modality: dict[str, dict[str, int]] = {}
    predictions_without_label = 0
    labels_without_prediction = 0
    matched_post_ids: set[str] = set()

    for post_id, handle, text, review_status, media_json in post_rows:
        if post_id in exclude_post_ids:
            continue
        human = _human_label(review_status)
        if human is None:
            continue
        prediction = predictions.get(post_id)
        if prediction is None:
            labels_without_prediction += 1
            continue
        matched_post_ids.add(post_id)

        agree = 1 if prediction == human else 0
        handle_stats = per_handle.setdefault(handle, {"agree": 0, "total": 0})
        handle_stats["total"] += 1
        handle_stats["agree"] += agree

        modality = "media" if json.loads(media_json) else "text_only"
        modality_stats = per_modality.setdefault(modality, {"agree": 0, "total": 0})
        modality_stats["total"] += 1
        modality_stats["agree"] += agree

        if human == "significant" and prediction == "significant":
            tp += 1
        elif human == "skip" and prediction == "significant":
            fp += 1
            disagreements.append({"post_id": post_id, "kind": "fp", "text": text, "handle": handle})
        elif human == "skip" and prediction == "skip":
            tn += 1
        elif human == "significant" and prediction == "skip":
            fn += 1
            disagreements.append({"post_id": post_id, "kind": "fn", "text": text, "handle": handle})

    predictions_without_label = sum(1 for post_id in predictions if post_id not in matched_post_ids)

    total = tp + fp + tn + fn
    agreement_pct = ((tp + tn) / total * 100) if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    fps = [d for d in disagreements if d["kind"] == "fp"]
    fns = [d for d in disagreements if d["kind"] == "fn"]
    half = 25
    sample = fps[:half] + fns[:half]

    return {
        "predictor": predictor,
        "total": total,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "agreement_pct": agreement_pct,
        "precision": precision,
        "recall": recall,
        "per_handle": per_handle,
        "per_modality": per_modality,
        "predictions_without_label": predictions_without_label,
        "labels_without_prediction": labels_without_prediction,
        "disagreement_sample": sample,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Gate agreement report: {report['predictor']}",
        "",
        f"Overall agreement: {report['agreement_pct']:.1f}% ({report['total']} scored posts)",
        f"Precision (positive class): {report['precision']:.3f}",
        f"Recall (positive class): {report['recall']:.3f}",
        "",
        "## Confusion matrix (human as truth)",
        "",
        f"- TP: {report['tp']}",
        f"- FP: {report['fp']}",
        f"- TN: {report['tn']}",
        f"- FN: {report['fn']}",
        "",
        f"Predictions without a human label: {report['predictions_without_label']}",
        f"Human labels without a prediction: {report['labels_without_prediction']}",
        "",
        "## Per-handle agreement",
        "",
    ]
    for handle, stats in sorted(report["per_handle"].items()):
        pct = (stats["agree"] / stats["total"] * 100) if stats["total"] else 0.0
        lines.append(f"- {handle}: {pct:.1f}% ({stats['agree']}/{stats['total']})")

    lines += ["", "## Per-modality agreement", ""]
    for modality, stats in sorted(report["per_modality"].items()):
        pct = (stats["agree"] / stats["total"] * 100) if stats["total"] else 0.0
        lines.append(f"- {modality}: {pct:.1f}% ({stats['agree']}/{stats['total']})")

    lines += ["", "## Disagreement sample (FP and FN, balanced)", ""]
    for d in report["disagreement_sample"]:
        snippet = d["text"][:200]
        lines.append(f"- [{d['kind']}] {d['post_id']} @{d['handle']}: {snippet}")

    return "\n".join(lines) + "\n"


def _reconfigure_stdout_utf8() -> None:
    """Force UTF-8 stdout so printing report text never crashes.

    Windows consoles default stdout to cp1252, which raises
    UnicodeEncodeError on non-cp1252 characters that regularly show up in
    scraped post text (e.g. em dashes, curly quotes, emoji). reconfigure is
    only present on real TextIOWrapper streams; pytest and other test
    runners may substitute a stream without it, so this is a no-op there.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def main() -> None:
    _reconfigure_stdout_utf8()
    parser = argparse.ArgumentParser(prog="python -m app.labeling.experiment")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--batch-size", type=int, default=50)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--predictor", required=True)
    ingest_parser.add_argument("--in", dest="in_path", required=True)

    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--predictor", required=True)
    score_parser.add_argument("--out")

    args = parser.parse_args()
    conn = connect(args.db)
    try:
        if args.command == "export":
            batch_count, post_count = export_batches(conn, args.out, args.batch_size)
            print(f"wrote {batch_count} batches, {post_count} posts")
        elif args.command == "ingest":
            ingested = ingest_predictions(conn, args.predictor, args.in_path)
            print(f"ingested {ingested} predictions")
        elif args.command == "score":
            report = score_predictor(conn, args.predictor)
            text = render_report(report)
            print(text)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
