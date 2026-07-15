import json
import sqlite3
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Set 2026-07-15 to match the maintainer's real X API balance ($5 remaining
# at $0.005/read = ~1000 more reads) on top of recorded usage (3955), not
# our original $20-budget guess of 4000 — the account's actual balance is
# the authoritative constraint. Recalibrate again from real trial-week data.
MAX_MONTHLY_POST_READS = 4900


class MediaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    media_type: str
    alt_text: str = ""


class XPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str
    handle: str
    posted_at: AwareDatetime
    text: str
    url: str
    fetched_at: AwareDatetime
    conversation_id: str = ""
    reply_context: str = ""
    media: list[MediaItem] = Field(default_factory=list)


def _media_from_row(media_json: str) -> list[MediaItem]:
    return [MediaItem.model_validate(item) for item in json.loads(media_json)]


def insert_new_posts(conn: sqlite3.Connection, posts: list[XPost]) -> int:
    inserted = 0
    for post in posts:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO x_posts
                (post_id, handle, posted_at, text, url, fetched_at,
                 conversation_id, reply_context, media_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.post_id,
                post.handle,
                post.posted_at.isoformat(),
                post.text,
                post.url,
                post.fetched_at.isoformat(),
                post.conversation_id,
                post.reply_context,
                json.dumps([m.model_dump() for m in post.media]),
            ),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def record_post_reads(conn: sqlite3.Connection, count: int, month: str | None = None) -> None:
    if month is None:
        month = datetime.now(UTC).strftime("%Y-%m")
    conn.execute(
        """
        INSERT INTO x_post_reads (month, post_reads) VALUES (?, ?)
        ON CONFLICT(month) DO UPDATE SET post_reads = post_reads + excluded.post_reads
        """,
        (month, count),
    )
    conn.commit()


def reads_remaining(conn: sqlite3.Connection, month: str | None = None) -> int:
    if month is None:
        month = datetime.now(UTC).strftime("%Y-%m")
    row = conn.execute(
        "SELECT post_reads FROM x_post_reads WHERE month = ?",
        (month,),
    ).fetchone()
    used = row[0] if row is not None else 0
    return MAX_MONTHLY_POST_READS - used


def unreviewed_posts(conn: sqlite3.Connection, limit: int = 50) -> list[XPost]:
    rows = conn.execute(
        """
        SELECT post_id, handle, posted_at, text, url, fetched_at,
               conversation_id, reply_context, media_json
        FROM x_posts
        WHERE review_status = 'unreviewed'
        ORDER BY posted_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        XPost(
            post_id=row[0],
            handle=row[1],
            posted_at=row[2],
            text=row[3],
            url=row[4],
            fetched_at=row[5],
            conversation_id=row[6],
            reply_context=row[7],
            media=_media_from_row(row[8]),
        )
        for row in rows
    ]


def unreviewed_thread_posts(
    conn: sqlite3.Connection, handle: str, conversation_id: str, exclude_post_id: str
) -> list[XPost]:
    """Other unreviewed posts by the same handle in the same conversation.

    Consolidates a thread of replies from one account into a single review
    action instead of forcing the maintainer to click through each reply
    separately (see plan 012).
    """
    if not conversation_id:
        return []
    rows = conn.execute(
        """
        SELECT post_id, handle, posted_at, text, url, fetched_at,
               conversation_id, reply_context, media_json
        FROM x_posts
        WHERE review_status = 'unreviewed'
          AND handle = ?
          AND conversation_id = ?
          AND post_id != ?
        ORDER BY posted_at ASC
        """,
        (handle, conversation_id, exclude_post_id),
    ).fetchall()
    return [
        XPost(
            post_id=row[0],
            handle=row[1],
            posted_at=row[2],
            text=row[3],
            url=row[4],
            fetched_at=row[5],
            conversation_id=row[6],
            reply_context=row[7],
            media=_media_from_row(row[8]),
        )
        for row in rows
    ]


def update_post_enrichment(conn: sqlite3.Connection, post: XPost) -> bool:
    """Backfill the three enrichment columns for one still-unreviewed post.

    The WHERE clause is the enforcement point for the "only unreviewed rows"
    rule (plan 014) — a reviewed row's label/input pairing must stay frozen,
    so the UPDATE is a no-op (rowcount 0) rather than a caller-side check.
    """
    cursor = conn.execute(
        """
        UPDATE x_posts
        SET conversation_id = ?, reply_context = ?, media_json = ?
        WHERE post_id = ? AND review_status = 'unreviewed'
        """,
        (
            post.conversation_id,
            post.reply_context,
            json.dumps([m.model_dump() for m in post.media]),
            post.post_id,
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_reviewed(conn: sqlite3.Connection, post_id: str, review_status: str) -> None:
    # 'significant' is the one-click positive label: relevant enough for gate
    # training, but without a rich CapturedSignal (that tier is 'captured').
    if review_status not in ("captured", "skipped", "significant"):
        raise ValueError(f"invalid review_status {review_status!r}")

    cursor = conn.execute(
        "UPDATE x_posts SET review_status = ? WHERE post_id = ? AND review_status = 'unreviewed'",
        (review_status, post_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"post {post_id} is not currently unreviewed")
