"""Trusted source/review ingestion with immutable records and validated links."""

import sqlite3
from datetime import datetime
from uuid import uuid4

from app.performance.paper import paper_observations
from app.performance.report import holding_episodes
from app.performance.storage import current_observations
from app.schemas.public_authoring import PublicSourceRecord, ThesisReview
from app.schemas.reporting import CoverageObservation, ValuationObservation


def save_public_source(conn: sqlite3.Connection, record: PublicSourceRecord) -> str:
    existing = conn.execute(
        "SELECT public_id, record_json FROM public_source_records WHERE revision_id=?",
        (record.revision_id,),
    ).fetchone()
    if existing:
        if PublicSourceRecord.model_validate_json(existing[1]) != record:
            raise ValueError("public source revision is immutable")
        return str(existing[0])
    public_id = "src_" + uuid4().hex
    if record.supersedes:
        previous = conn.execute(
            "SELECT public_id, record_json FROM public_source_records WHERE revision_id=?",
            (record.supersedes,),
        ).fetchone()
        if previous is None:
            raise ValueError("source revision predecessor is missing")
        prior = PublicSourceRecord.model_validate_json(previous[1])
        if prior.source_ref != record.source_ref or prior.recorded_at > record.recorded_at:
            raise ValueError("source revision changes identity or precedes its predecessor")
        public_id = previous[0]
    conn.execute(
        "INSERT INTO public_source_records VALUES (?, ?, ?, ?, ?)",
        (
            record.revision_id,
            record.source_ref,
            public_id,
            record.supersedes,
            record.model_dump_json(),
        ),
    )
    return public_id


def save_thesis_review(conn: sqlite3.Connection, review: ThesisReview) -> None:
    existing = conn.execute(
        "SELECT record_json FROM thesis_reviews WHERE review_id=?", (review.review_id,)
    ).fetchone()
    if existing:
        if ThesisReview.model_validate_json(existing[0]) != review:
            raise ValueError("thesis review is immutable")
        return
    observations = current_observations(conn, mode=review.mode, account_id=review.account_id)
    if not observations and review.mode == "paper" and review.account_id == "paper":
        observations, issue = paper_observations(conn)
        if issue:
            raise ValueError("paper holding history is inconsistent")
    values = sorted(
        [
            o
            for o in observations
            if isinstance(o, ValuationObservation) and o.phase not in {"before_flow", "after_flow"}
        ],
        key=lambda o: o.occurred_at,
    )
    if not values:
        raise ValueError("holding episode history is unavailable")
    coverage = [o for o in observations if isinstance(o, CoverageObservation)]
    history = holding_episodes(values, observations, coverage, limit=None)
    episode = next(
        (item for item in history["items"] if item["episode_id"] == review.episode_id), None
    )
    if episode is None or episode["ticker"] != review.ticker:
        raise ValueError("review does not match an observed holding episode")
    if review.reviewed_at < datetime.fromisoformat(episode["first_observed_at"]):
        raise ValueError("review precedes holding episode")
    if review.runtime_attempt_id:
        from app.storage.runtime import get_attempt, get_run

        attempt = get_attempt(conn, review.runtime_attempt_id)
        runtime_run = get_run(conn, attempt.run_id)
        if (
            runtime_run.mode != review.mode
            or runtime_run.account_id != review.account_id
            or review.reasoning_run_id != runtime_run.reasoning_run_id
        ):
            raise ValueError("review attempt belongs to a different run or account")
        if (
            not attempt.started_at
            <= review.reviewed_at
            <= (attempt.finished_at or attempt.heartbeat_at)
        ):
            raise ValueError("review falls outside its recorded attempt")
    elif review.reasoning_run_id:
        run = conn.execute(
            "SELECT r.started_at, r.completed_at, r.execution_profile_id, s.snapshot_json "
            "FROM reasoning_runs r JOIN live_portfolio_snapshots s "
            "ON s.portfolio_snapshot_id=r.portfolio_snapshot_id WHERE reasoning_run_id=?",
            (review.reasoning_run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("review run or bound snapshot is missing")
        from app.schemas.live_execution import LivePortfolioSnapshot

        snapshot = LivePortfolioSnapshot.model_validate_json(run[3])
        if (
            review.mode != "live"
            or snapshot.broker_account_fingerprint != review.account_id
            or snapshot.execution_profile_id != run[2]
        ):
            raise ValueError("review run belongs to a different account")
        if review.reviewed_at < datetime.fromisoformat(run[0]) or (
            run[1] and review.reviewed_at > datetime.fromisoformat(run[1])
        ):
            raise ValueError("review falls outside its recorded run")
    conn.execute(
        "INSERT INTO thesis_reviews VALUES (?, ?, ?, ?, ?, ?)",
        (
            review.review_id,
            review.mode,
            review.account_id,
            review.episode_id,
            review.reviewed_at.isoformat(),
            review.model_dump_json(),
        ),
    )
