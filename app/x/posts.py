import sqlite3
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict

MAX_MONTHLY_POST_READS = 4000


class XPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str
    handle: str
    posted_at: AwareDatetime
    text: str
    url: str
    fetched_at: AwareDatetime


def insert_new_posts(conn: sqlite3.Connection, posts: list[XPost]) -> int:
    inserted = 0
    for post in posts:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO x_posts (post_id, handle, posted_at, text, url, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                post.post_id,
                post.handle,
                post.posted_at.isoformat(),
                post.text,
                post.url,
                post.fetched_at.isoformat(),
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
        SELECT post_id, handle, posted_at, text, url, fetched_at FROM x_posts
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
        )
        for row in rows
    ]


def mark_reviewed(conn: sqlite3.Connection, post_id: str, review_status: str) -> None:
    if review_status not in ("captured", "skipped"):
        raise ValueError(f"invalid review_status {review_status!r}")

    cursor = conn.execute(
        "UPDATE x_posts SET review_status = ? WHERE post_id = ? AND review_status = 'unreviewed'",
        (review_status, post_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"post {post_id} is not currently unreviewed")
