import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.reason.runtime_prepare import assemble_intake
from app.reason.worker import execute_attempt, unreviewed_holdings
from app.schemas.reasoning_run import ReasoningRun
from app.schemas.runtime import AuthoredOutput, AuthoredThesisReview, RuntimeRun
from app.storage.database import connect
from app.storage.holding_reviews import live_holding_episodes
from app.storage.records import save_reasoning_run
from app.storage.runtime import save_run
from tests.reason.test_live_submit import _profile
from tests.storage.test_holding_reviews import ACCOUNT, snapshot_at

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


def test_a_due_holding_needs_a_verdict_a_summary_and_an_opened_source(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    complete = AuthoredThesisReview(
        episode_id=episode,
        ticker="NVDA",
        state="intact",
        summary="Data-center demand still outruns supply at today's price.",
        sources_opened=["https://investor.nvidia.com/"],
    )

    shortfalls = [
        unreviewed_holdings(conn, run, AuthoredOutput(thesis_reviews=reviews, public_summary="x"))
        for reviews in (
            [],
            [complete.model_copy(update={"state": "not_reviewed"})],
            [complete.model_copy(update={"sources_opened": []})],
            [complete],
        )
    ]

    assert shortfalls[0] and "NVDA is due a thesis review" in shortfalls[0]
    assert shortfalls[1] and "state other than not_reviewed" in shortfalls[1]
    assert shortfalls[2] and "no opened source URL" in shortfalls[2]
    assert shortfalls[3] is None
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
        reviews = (
            []
            if len(prompts) == 1
            else [
                AuthoredThesisReview(
                    episode_id=episode,
                    ticker="NVDA",
                    state="intact",
                    summary="Would still buy it today at this price.",
                    sources_opened=["https://investor.nvidia.com/"],
                )
            ]
        )
        return AuthoredOutput(thesis_reviews=reviews, public_summary="Holdings reviewed.")

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
    assert "sources_opened" not in stored[0]
    conn.close()
