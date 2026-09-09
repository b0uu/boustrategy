import json
import re
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from app.events.store import upcoming_events
from app.x.calendar import slot_should_run
from app.x.posts import MAX_MONTHLY_POST_READS, reads_remaining

LINK_ONLY_MAX_CHARS = 40
_URL_PATTERN = re.compile(r"https?://\S+")
_RANKS = ("headline", "notable", "context")
_SLOT_ORDER = {"morning": 0, "midday": 1, "close": 2, "weekly": 3}


def _now() -> datetime:
    return datetime.now(UTC)


def _export_posts(conn: sqlite3.Connection, out_dir: Path, cutoff: str) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT p.post_id, p.handle, p.posted_at, p.text, p.reply_context, p.media_json, p.url
        FROM x_posts AS p
        LEFT JOIN x_route_decisions AS r ON r.post_id = p.post_id
        WHERE p.review_status = 'unreviewed' AND r.post_id IS NULL AND p.fetched_at >= ?
        ORDER BY p.post_id ASC
        """,
        (cutoff,),
    ).fetchall()
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.glob("batch_*.jsonl")):
        raise ValueError("export requires a directory without previous generated batches")
    for batch_number, start in enumerate(range(0, len(rows), 50), 1):
        lines = []
        for post_id, handle, posted_at, text, reply_context, media_json, url in rows[
            start : start + 50
        ]:
            lines.append(
                json.dumps(
                    {
                        "post_id": post_id,
                        "handle": handle,
                        "posted_at": posted_at,
                        "text": text,
                        "reply_context": reply_context,
                        "media": json.loads(media_json),
                        "url": url,
                    }
                )
            )
        (out_dir / f"batch_{batch_number:03d}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    rubric = Path("docs/x_pipeline/RUBRIC.md")
    if rubric.exists():
        shutil.copyfile(rubric, out_dir / "RUBRIC.md")
    else:
        print("notice: docs/x_pipeline/RUBRIC.md is not present; continuing without rubric")
    return (len(range(0, len(rows), 50)), len(rows))


def cycle(
    conn: sqlite3.Connection,
    slot: str,
    run_date: date,
    out_dir: str | Path,
    fetch: Callable[[sqlite3.Connection], None],
) -> None:
    if slot_should_run(run_date, slot) is None:
        print(f"{run_date.isoformat()} {slot}: calendar no-op")
        return

    run_id = f"{run_date.isoformat()}-{slot}"
    existing = conn.execute(
        "SELECT status, started_at, reads_used FROM x_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    prior_reads = 0
    if existing is not None:
        if existing[0] in ("routed", "digested"):
            print(f"{run_id}: already ran")
            return
        if existing[0] != "failed":
            raise RuntimeError(f"{run_id} is stuck with status {existing[0]}")
        started_at = existing[1]
        prior_reads = existing[2]
        conn.execute(
            "UPDATE x_runs SET status = 'started', finished_at = NULL WHERE run_id = ?",
            (run_id,),
        )
    else:
        started_at = _now().isoformat()
        conn.execute(
            "INSERT INTO x_runs (run_id, slot, started_at) VALUES (?, ?, ?)",
            (run_id, slot, started_at),
        )
    conn.commit()
    if slot == "weekly":
        conn.execute(
            "UPDATE x_runs SET status = 'routed', finished_at = ? WHERE run_id = ?",
            (_now().isoformat(), run_id),
        )
        conn.commit()
        print(f"{run_id}: weekly ledger anchor created")
        return

    reads_before = reads_remaining(conn)
    try:
        fetch(conn)
    except Exception:
        reads_after = reads_remaining(conn)
        fetched = conn.execute(
            "SELECT COUNT(*) FROM x_posts WHERE fetched_at >= ?", (started_at,)
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE x_runs SET posts_fetched = ?, reads_used = ?, status = 'failed', finished_at = ?
            WHERE run_id = ?
            """,
            (fetched, prior_reads + reads_before - reads_after, _now().isoformat(), run_id),
        )
        conn.commit()
        raise
    reads_after = reads_remaining(conn)
    new_rows = conn.execute(
        """
        SELECT post_id, text, media_json FROM x_posts
        WHERE review_status = 'unreviewed' AND fetched_at >= ?
        """,
        (started_at,),
    ).fetchall()
    decided_at = _now().isoformat()
    for post_id, text, media_json in new_rows:
        if _URL_PATTERN.search(text) and not json.loads(media_json):
            remainder = _URL_PATTERN.sub("", text)
            if len("".join(remainder.split())) <= LINK_ONLY_MAX_CHARS:
                conn.execute(
                    """
                    INSERT INTO x_route_decisions
                        (post_id, run_id, route, predictor, decided_at)
                    VALUES (?, ?, 'article_queue', 'code:link_only', ?)
                    """,
                    (post_id, run_id, decided_at),
                )
                conn.execute(
                    "INSERT INTO x_article_queue (post_id, queued_at) VALUES (?, ?)",
                    (post_id, decided_at),
                )

    previous = conn.execute(
        """
        SELECT started_at FROM x_runs
        WHERE run_id != ? AND finished_at IS NOT NULL
        ORDER BY finished_at DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    cutoff = previous[0] if previous is not None else (_now() - timedelta(hours=24)).isoformat()
    _, exported = _export_posts(conn, Path(out_dir), cutoff)
    conn.execute(
        """
        UPDATE x_runs SET posts_fetched = ?, posts_exported = ?, reads_used = ?,
            status = 'exported', finished_at = ? WHERE run_id = ?
        """,
        (
            len(new_rows),
            exported,
            prior_reads + reads_before - reads_after,
            _now().isoformat(),
            run_id,
        ),
    )
    conn.commit()
    print(
        f"{run_id}: fetched={len(new_rows)} exported={exported} "
        f"reads_used={reads_before - reads_after} remaining={reads_after}"
    )


def route_predictions(
    conn: sqlite3.Connection, run_id: str, predictor: str, in_path: str | Path
) -> int:
    if conn.execute("SELECT 1 FROM x_runs WHERE run_id = ?", (run_id,)).fetchone() is None:
        raise ValueError(f"unknown run_id {run_id!r}")
    path = Path(in_path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    records = []
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))

    for record in records:
        post_id = record["post_id"]
        prediction = record["prediction"]
        rank = record.get("rank", "")
        if prediction not in ("significant", "skip"):
            raise ValueError(f"invalid prediction {prediction!r} for post {post_id}")
        if prediction == "significant" and rank not in _RANKS:
            raise ValueError(f"significant prediction requires valid rank for post {post_id}")
        if prediction == "skip" and rank:
            raise ValueError(f"skip prediction must not have rank for post {post_id}")
        if conn.execute("SELECT 1 FROM x_posts WHERE post_id = ?", (post_id,)).fetchone() is None:
            raise ValueError(f"unknown post_id {post_id!r} not present in x_posts")
        prior = conn.execute(
            "SELECT run_id FROM x_route_decisions WHERE post_id = ?", (post_id,)
        ).fetchone()
        if prior is not None and prior[0] != run_id:
            raise ValueError(f"post {post_id} already routed by run {prior[0]}")

    decided_at = _now().isoformat()
    for record in records:
        conn.execute(
            """
            INSERT OR REPLACE INTO x_route_decisions
                (post_id, run_id, route, rank, reason, predictor, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["post_id"],
                run_id,
                "digest" if record["prediction"] == "significant" else "skip",
                record.get("rank", ""),
                record.get("reason", ""),
                predictor,
                decided_at,
            ),
        )
    conn.execute(
        "UPDATE x_runs SET status = 'routed', finished_at = ? WHERE run_id = ?",
        (decided_at, run_id),
    )
    conn.commit()
    digest_count = sum(record["prediction"] == "significant" for record in records)
    print(f"{run_id}: routed digest={digest_count} skip={len(records) - digest_count}")
    return len(records)


def store_note(
    conn: sqlite3.Connection, note_date: date, slot: str, author: str, synthesis: str
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO x_digest_notes
            (note_date, slot, synthesis, author, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (note_date.isoformat(), slot, synthesis, author, _now().isoformat()),
    )
    conn.commit()


def _post_lines(rows: Sequence[sqlite3.Row | tuple[object, ...]], snippet: int) -> list[str]:
    lines: list[str] = []
    for handle, posted_at, text, reason, url in rows:
        normalized_text = " ".join(str(text).split())
        lines.append(f"- @{handle} | {posted_at} | {normalized_text[:snippet]} | {reason} | {url}")
    return lines


def render_digest(conn: sqlite3.Connection, digest_date: date, out_path: str | Path) -> str:
    day = digest_date.isoformat()
    runs = conn.execute(
        """
        SELECT run_id, slot, posts_fetched, posts_exported, reads_used, status
        FROM x_runs WHERE substr(run_id, 1, 10) = ? ORDER BY started_at
        """,
        (day,),
    ).fetchall()
    ranked: dict[str, list[tuple[object, ...]]] = {}
    for rank in _RANKS:
        ranked[rank] = conn.execute(
            """
            SELECT p.handle, p.posted_at, p.text, r.reason, p.url
            FROM x_route_decisions AS r JOIN x_posts AS p ON p.post_id = r.post_id
            WHERE r.route = 'digest' AND r.rank = ? AND substr(r.run_id, 1, 10) = ?
            ORDER BY p.posted_at
            """,
            (rank, day),
        ).fetchall()
    roster = conn.execute("SELECT COUNT(*) FROM x_accounts WHERE status = 'active'").fetchone()[0]
    completed = sum(1 for row in runs if row[5] in ("routed", "digested"))
    # Keep the marker off the section heading used as the intake extraction boundary.
    marker = " ACTIONABLE" if ranked["headline"] else ""
    lines = [
        f"# X digest: {day}{marker}",
        "",
        f"Runs completed: {completed}",
        f"Roster size: {roster}",
    ]
    for title, rank, snippet in (
        ("Actionable", "headline", 280),
        ("Notable", "notable", 200),
        ("Context", "context", 160),
    ):
        lines += ["", f"## {title}", "", *_post_lines(ranked[rank], snippet)]
    articles = conn.execute(
        """
        SELECT p.url, q.queued_at FROM x_article_queue AS q
        JOIN x_posts AS p ON p.post_id = q.post_id
        WHERE q.status = 'pending' ORDER BY q.queued_at
        """
    ).fetchall()
    lines += ["", "## Article queue", ""]
    lines += [f"- {url} | queued {queued_at}" for url, queued_at in articles]
    events = upcoming_events(conn, digest_date, 7)
    if events:
        lines += ["", "## Calendar", ""]
        for event_date, event_type, ticker, label in events:
            subject = ticker or "FOMC"
            lines.append(f"- {event_date} | {event_type} | {subject} | {label}")
    notes = conn.execute(
        "SELECT slot, synthesis, author FROM x_digest_notes WHERE note_date = ?", (day,)
    ).fetchall()
    notes.sort(key=lambda row: _SLOT_ORDER.get(row[0], 99))
    lines += ["", "## Synthesis", ""]
    for slot, synthesis, author in notes:
        lines += [f"### {slot} ({author})", "", synthesis, ""]
    remaining = reads_remaining(conn, day[:7])
    lines += ["## Ops", ""]
    for run_id, slot, fetched, exported, reads_used, status in runs:
        routed = conn.execute(
            "SELECT COUNT(*) FROM x_route_decisions WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        displayed_status = "completed" if status in ("routed", "digested") else status
        lines.append(
            f"- {slot}: fetched={fetched} exported={exported} routed={routed} "
            f"reads_used={reads_used} status={displayed_status}"
        )
    lines.append(
        f"- monthly reads: used={MAX_MONTHLY_POST_READS - remaining} remaining={remaining}"
    )
    text = "\n".join(lines).rstrip() + "\n"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    conn.execute(
        """
        UPDATE x_runs SET status = 'digested'
        WHERE substr(run_id, 1, 10) = ? AND status = 'routed'
        """,
        (day,),
    )
    conn.commit()
    return text


def render_weekly(conn: sqlite3.Connection, end_date: date, out_path: str | Path) -> str:
    end = end_date.isoformat()
    start = (end_date - timedelta(days=6)).isoformat()
    headlines = conn.execute(
        """
        SELECT p.handle, p.posted_at, p.text, r.reason, p.url
        FROM x_route_decisions AS r JOIN x_posts AS p ON p.post_id = r.post_id
        WHERE r.route = 'digest' AND r.rank = 'headline'
          AND substr(r.run_id, 1, 10) BETWEEN ? AND ? ORDER BY p.posted_at
        """,
        (start, end),
    ).fetchall()
    accounts = conn.execute(
        """
        SELECT a.handle,
          (SELECT COUNT(*) FROM x_posts p WHERE p.handle = a.handle
           AND substr(p.fetched_at, 1, 10) BETWEEN ? AND ?) AS fetched,
          SUM(CASE WHEN r.rank = 'headline' THEN 1 ELSE 0 END),
          SUM(CASE WHEN r.rank = 'notable' THEN 1 ELSE 0 END),
          SUM(CASE WHEN r.rank = 'context' THEN 1 ELSE 0 END)
        FROM x_accounts a LEFT JOIN x_posts p2 ON p2.handle = a.handle
        LEFT JOIN x_route_decisions r ON r.post_id = p2.post_id
          AND substr(r.run_id, 1, 10) BETWEEN ? AND ?
        GROUP BY a.handle ORDER BY a.handle
        """,
        (start, end, start, end),
    ).fetchall()
    articles = conn.execute(
        """
        SELECT p.url, q.status, q.resolution FROM x_article_queue q
        JOIN x_posts p ON p.post_id = q.post_id ORDER BY q.queued_at
        """
    ).fetchall()
    runs = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(posts_fetched), 0), COALESCE(SUM(posts_exported), 0),
               COALESCE(SUM(reads_used), 0)
        FROM x_runs WHERE substr(run_id, 1, 10) BETWEEN ? AND ?
        """,
        (start, end),
    ).fetchone()
    routed = conn.execute(
        """
        SELECT COUNT(*) FROM x_route_decisions
        WHERE substr(run_id, 1, 10) BETWEEN ? AND ?
        """,
        (start, end),
    ).fetchone()[0]
    lines = [f"# X weekly digest: {end}", "", "## Headlines", "", *_post_lines(headlines, 280)]
    lines += ["", "## Per-account counts", ""]
    for handle, fetched, headline, notable, context in accounts:
        lines.append(
            f"- @{handle}: fetched={fetched} headline={headline} "
            f"notable={notable} context={context}"
        )
    lines += ["", "## Article queue", ""]
    lines += [f"- {url} | {status} | {resolution}" for url, status, resolution in articles]
    lines += ["", "## Synthesis", ""]
    note = conn.execute(
        "SELECT synthesis, author FROM x_digest_notes WHERE note_date = ? AND slot = 'weekly'",
        (end,),
    ).fetchone()
    if note is not None:
        lines += [f"### weekly ({note[1]})", "", note[0]]
    lines += [
        "",
        "## Ops",
        "",
        f"- runs={runs[0]} fetched={runs[1]} exported={runs[2]} "
        f"routed={routed} reads_used={runs[3]}",
    ]
    text = "\n".join(lines).rstrip() + "\n"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    conn.execute("UPDATE x_runs SET status = 'digested' WHERE run_id = ?", (f"{end}-weekly",))
    conn.commit()
    return text


_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4"}


def _fetch_bytes(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.content


def download_media(
    run_dir: str | Path, fetch: Callable[[str], bytes] = _fetch_bytes
) -> dict[str, int]:
    """Fetch every media attachment referenced by a run export into ``<run>/media``.

    Windows-native TLS (curl.exe, Invoke-WebRequest) has no credential store inside
    Codex's restricted-token sandbox, while httpx carries its own CA bundle. The
    judging session downloads through this command instead of improvising a shell.
    """
    folder = Path(run_dir)
    batches = sorted(folder.glob("batch_*.jsonl"))
    if not batches:
        raise ValueError(f"no batch exports under {folder}")
    media_dir = folder / "media"
    media_dir.mkdir(exist_ok=True)
    counts = {"downloaded": 0, "cached": 0, "failed": 0}
    for batch in batches:
        for line in batch.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            for index, item in enumerate(record.get("media", []), 1):
                url = item.get("url", "")
                if not url:
                    continue
                suffix = Path(url.split("?", 1)[0]).suffix.lower()
                if suffix not in _MEDIA_SUFFIXES:
                    suffix = ".jpg"
                dest = media_dir / f"{record['post_id']}_{index}{suffix}"
                if dest.exists():
                    counts["cached"] += 1
                    continue
                try:
                    dest.write_bytes(fetch(url))
                    counts["downloaded"] += 1
                except (httpx.HTTPError, OSError) as error:
                    dest.with_suffix(dest.suffix + ".failed").write_text(
                        f"{url}\n{type(error).__name__}: {error}\n", encoding="utf-8"
                    )
                    counts["failed"] += 1
    print(
        f"media: downloaded={counts['downloaded']} cached={counts['cached']} "
        f"failed={counts['failed']} dir={media_dir}"
    )
    return counts
