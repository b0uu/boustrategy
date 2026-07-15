import sqlite3
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.x.posts import mark_reviewed


class ClaimType(StrEnum):
    FACT = "fact"
    INTERPRETATION = "interpretation"


class Stance(StrEnum):
    IDEA_SOURCE = "idea_source"
    CONFIRMATION = "confirmation"
    COUNTER_THESIS = "counter_thesis"
    CROWDING_WARNING = "crowding_warning"
    THEME_DISCOVERY = "theme_discovery"


class Horizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class ScrutinyVerdict(StrEnum):
    SUBSTANTIATED = "substantiated"
    UNSUPPORTED = "unsupported"
    WRONG = "wrong"
    NONSENSE = "nonsense"
    # Claim significance is beyond the labeler's expertise to judge: neutral
    # for the account scrutiny ledger (no credit, no penalty) and a revisit
    # queue for the future expert-reader stage.
    CANNOT_ASSESS = "cannot_assess"


class CapturedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    captured_at: AwareDatetime
    post_url: str
    handle: str
    posted_at: AwareDatetime
    primary_theme_id: str
    tickers: list[str] = Field(default_factory=list)
    claim: str
    claim_type: ClaimType
    stance: Stance
    horizon: Horizon
    scrutiny_verdict: ScrutinyVerdict
    why_it_matters: str


def save_signal(conn: sqlite3.Connection, signal: CapturedSignal) -> bool:
    signal_json = signal.model_dump_json()
    existing = conn.execute(
        "SELECT signal_json FROM x_signals WHERE entry_id = ?",
        (signal.entry_id,),
    ).fetchone()
    if existing is not None:
        if existing[0] == signal_json:
            return False
        raise ValueError(f"signal {signal.entry_id} already exists with different content")

    conn.execute(
        """
        INSERT INTO x_signals (entry_id, post_id, handle, signal_json, captured_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            signal.entry_id,
            signal.post_id,
            signal.handle,
            signal_json,
            signal.captured_at.isoformat(),
        ),
    )
    conn.commit()

    post_row = conn.execute(
        "SELECT review_status FROM x_posts WHERE post_id = ?",
        (signal.post_id,),
    ).fetchone()
    if post_row is not None and post_row[0] == "unreviewed":
        mark_reviewed(conn, signal.post_id, "captured")

    return True
