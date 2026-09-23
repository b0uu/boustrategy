import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.reason.runtime_prepare import assemble_intake
from app.reason.worker import execute_attempt, unreviewed_holdings
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.reasoning_run import ReasoningRun
from app.schemas.runtime import (
    AuthoredEarningsDate,
    AuthoredOutput,
    AuthoredThesisReview,
    AuthoredXTriage,
    RuntimeRun,
)
from app.storage.database import connect
from app.storage.holding_reviews import live_holding_episodes
from app.storage.records import save_reasoning_run
from app.storage.runtime import save_run
from tests.fixtures.decision_records import valid_decision_record_data
from tests.reason.test_live_submit import _profile
from tests.storage.test_holding_reviews import ACCOUNT, review, snapshot_at, x_post

# Wednesday 2026-09-23, 13:00 ET: the midday review point has passed and the market is open.
WEDNESDAY_MIDDAY = datetime(2026, 9, 23, 17, 0, tzinfo=UTC)


def live_review(conn: sqlite3.Connection, folder: Path) -> RuntimeRun:
    snapshot = snapshot_at(conn, folder, WEDNESDAY_MIDDAY, {"NVDA": (0.1, 200, 230)})
    path = folder / "live-intake.md"
    path.write_text("Deliberate live intake", encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    save_reasoning_run(
        conn,
        ReasoningRun(
            reasoning_run_id="legacy-live",
            session_date=WEDNESDAY_MIDDAY.date(),
            slot="midday",
            execution_profile_id="codex",
            model_label="review-model",
            shared_bundle_path=str(path),
            shared_bundle_sha256=checksum,
            portfolio_snapshot_id=snapshot.portfolio_snapshot_id,
            started_at=WEDNESDAY_MIDDAY,
        ),
    )
    conn.execute(
        "INSERT INTO regime_snapshots VALUES "
        "('2026-09-22','GREEN','GREEN',5,'{}','2026-09-22T21:00:00+00:00')"
    )
    conn.commit()
    return RuntimeRun(
        run_id="live-runtime",
        mode="live",
        account_id=ACCOUNT,
        execution_profile_id="codex",
        session_date=WEDNESDAY_MIDDAY.date(),
        slot="midday",
        prepared_at=WEDNESDAY_MIDDAY,
        intake_path=str(path),
        intake_sha256=checksum,
        reasoning_run_id="legacy-live",
    )


def test_a_live_intake_shows_cost_basis_and_the_holdings_due_a_review(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]

    prepared = assemble_intake(conn, run, tmp_path / "out", _profile())

    text = Path(prepared.intake_path).read_text(encoding="utf-8")
    facts = json.loads(text.split("# Starting portfolio facts\n\n")[1].split("\n\n", 1)[0])
    due = json.loads(text.split("# Holdings due for thesis review\n\n")[1].split("\n\n", 1)[0])
    assert facts["positions"][0] | {"primary_theme_id": None} == {
        "ticker": "NVDA",
        "market_value": 23.0,
        "primary_theme_id": None,
        "weight_percent": 23.0,
        "quantity": "0.1",
        "average_cost": "200.0",
        "price": "230.0",
        "unrealized_return_percent": 15.0,
    }
    assert [(item["episode_id"], item["reasons"]) for item in due] == [
        (episode, ["scheduled_review"])
    ]
    conn.close()


def complete_review(episode: str) -> AuthoredThesisReview:
    return AuthoredThesisReview(
        episode_id=episode,
        ticker="NVDA",
        state="intact",
        summary="Would still own it at today's price.",
        sources_opened=["https://investor.nvidia.com/"],
    )


def test_a_due_holding_needs_a_summary_and_an_opened_source(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    complete = complete_review(episode)

    shortfalls = [
        unreviewed_holdings(conn, run, AuthoredOutput(thesis_reviews=reviews, public_summary="x"))
        for reviews in (
            [],
            [complete.model_copy(update={"summary": None})],
            [complete.model_copy(update={"sources_opened": []})],
            [complete.model_copy(update={"episode_id": "live:guessed"})],
            [complete],
        )
    ]

    assert shortfalls[0] and "NVDA is due a thesis review" in shortfalls[0]
    assert shortfalls[1] and "needs a summary" in shortfalls[1]
    assert shortfalls[2] and "no opened source URL" in shortfalls[2]
    assert shortfalls[3] and "isn't a current holding episode" in shortfalls[3]
    assert shortfalls[4] is None
    conn.close()


def test_an_invalidated_holding_must_be_sold_or_trimmed_while_the_market_is_open(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    invalidated = complete_review(episode).model_copy(update={"state": "invalidated"})
    sell = InvestmentDecisionRecord.model_validate(
        {**valid_decision_record_data(), "ticker": "NVDA", "decision": "SELL"}
    )

    kept = unreviewed_holdings(
        conn, run, AuthoredOutput(thesis_reviews=[invalidated], public_summary="x")
    )
    sold = unreviewed_holdings(
        conn,
        run,
        AuthoredOutput(decisions=[sell], thesis_reviews=[invalidated], public_summary="x"),
    )
    closed = unreviewed_holdings(
        conn,
        run,
        AuthoredOutput(thesis_reviews=[invalidated], public_summary="x"),
        trading_open=False,
    )

    assert kept and "record a SELL or TRIM" in kept
    assert sold is None
    assert closed is None
    conn.close()


def test_every_listed_x_headline_needs_a_verdict_and_a_thesis_changing_one_a_review(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    # Reviewed after the midday point, so only the headline that follows can call for another.
    run = live_review(conn, tmp_path).model_copy(
        update={"prepared_at": WEDNESDAY_MIDDAY + timedelta(hours=1)}
    )
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", WEDNESDAY_MIDDAY)
    x_post(
        conn,
        "1",
        "Blackwell racks are sold out through next year",
        "headline",
        ["NVDA"],
        WEDNESDAY_MIDDAY + timedelta(minutes=30),
    )
    verdict = AuthoredXTriage(
        post_id="1", ticker="NVDA", changes_thesis=False, note="Already in the thesis."
    )

    shortfalls = [
        unreviewed_holdings(
            conn,
            run,
            AuthoredOutput(x_triage=triage, thesis_reviews=reviews, public_summary="x"),
        )
        for triage, reviews in (
            ([], []),
            ([verdict], []),
            ([verdict.model_copy(update={"changes_thesis": True})], []),
            ([verdict.model_copy(update={"changes_thesis": True})], [complete_review(episode)]),
        )
    ]

    assert shortfalls[0] and "has no x_triage verdict" in shortfalls[0]
    assert shortfalls[1] is None
    assert shortfalls[2] and "judged thesis-changing" in shortfalls[2]
    assert shortfalls[3] is None
    conn.close()


def test_a_thesis_changing_headline_is_recorded_and_its_review_starts_the_cooldown(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path).model_copy(
        update={"prepared_at": WEDNESDAY_MIDDAY + timedelta(minutes=2)}
    )
    save_run(conn, run)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    x_post(
        conn,
        "1",
        "Blackwell racks are sold out through next year",
        "headline",
        ["NVDA"],
        WEDNESDAY_MIDDAY + timedelta(minutes=1),
    )
    conn.commit()

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        return AuthoredOutput(
            thesis_reviews=[complete_review(episode)],
            x_triage=[
                AuthoredXTriage(
                    post_id="1", ticker="NVDA", changes_thesis=True, note="Supply outlook moved."
                )
            ],
            public_summary="Holdings reviewed.",
        )

    execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY + timedelta(minutes=3),
        log_root=tmp_path / "logs",
    )

    stored = json.loads(conn.execute("SELECT record_json FROM thesis_reviews").fetchone()[0])
    assert stored["review_reasons"] == ["scheduled_review", "x_digest"]
    assert conn.execute("SELECT post_id, ticker, changes_thesis FROM x_triage").fetchall() == [
        ("1", "NVDA", 1)
    ]
    conn.close()


def test_a_review_that_skips_a_due_holding_is_retried_and_its_review_recorded(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    save_run(conn, run)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    prompts: list[str] = []

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        prompts.append(prompt)
        reviews = [] if len(prompts) == 1 else [complete_review(episode)]
        return AuthoredOutput(
            thesis_reviews=reviews,
            earnings_dates=[
                AuthoredEarningsDate(
                    ticker="NVDA",
                    event_date=date(2026, 11, 18),
                    confirmed=True,
                    source_url="https://investor.nvidia.com/events",
                )
            ],
            public_summary="Holdings reviewed.",
        )

    attempt = execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY,
        log_root=tmp_path / "logs",
    )

    stored = [json.loads(row[0]) for row in conn.execute("SELECT record_json FROM thesis_reviews")]
    assert attempt.status == "no_action"
    assert "holding NVDA is due a thesis review" in prompts[1]
    assert [(item["episode_id"], item["state"]) for item in stored] == [(episode, "intact")]
    assert stored[0]["review_reasons"] == ["scheduled_review"]
    assert "sources_opened" not in stored[0]
    assert conn.execute(
        "SELECT ticker, event_date, label, source FROM calendar_events"
    ).fetchall() == [("NVDA", "2026-11-18", "confirmed", "agent")]
    conn.close()


def test_a_review_that_still_skips_a_due_holding_is_accepted_without_its_new_buys(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    save_run(conn, run)

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        buy = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "buy"}
        )
        return AuthoredOutput(decisions=[buy], public_summary="A new idea, holdings skipped.")

    attempt = execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY,
        log_root=tmp_path / "logs",
    )

    research = json.loads((tmp_path / "logs" / attempt.attempt_id / "research.json").read_text())
    assert attempt.status == "no_action"
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 0
    assert "NVDA is due a thesis review" in research["passes"][1]["review_gap"]
    assert attempt.public_summary and "held back this review's new buys" in attempt.public_summary
    conn.close()


def test_a_holdings_gap_with_no_time_left_to_retry_is_still_accepted(
    tmp_path: Path, monkeypatch: Any
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    save_run(conn, run)
    ticks = iter([0.0, 1790.0])
    monkeypatch.setattr("app.reason.worker.time", SimpleNamespace(monotonic=lambda: next(ticks)))
    calls = 0

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        nonlocal calls
        calls += 1
        return AuthoredOutput(public_summary="Holdings skipped.")

    attempt = execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY,
        log_root=tmp_path / "logs",
        timeout_seconds=1800,
    )

    assert (attempt.status, calls) == ("no_action", 1)
    conn.close()
