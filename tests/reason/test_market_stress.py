import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.broker.session import BrokerSessionFailure
from app.reason.events import event_review_cause
from app.reason.worker import (
    execute_attempt,
    unanswered_challengers,
    unanswered_exposure,
    unreviewed_holdings,
)
from app.schemas.runtime import AuthoredExposureDecision, AuthoredOutput, RuntimeRun
from app.storage.database import connect
from app.storage.holding_reviews import live_holding_episodes
from app.storage.records import get_live_portfolio_snapshot
from app.storage.runtime import save_run
from app.triggers.store import insert_trigger
from tests.reason.test_live_submit import _profile
from tests.reason.test_research_hunt import candidate, events
from tests.reason.test_thesis_review_gate import (
    FULLY_INVESTED,
    WEDNESDAY_MIDDAY,
    amd_clears_the_bar,
    complete_review,
    decision,
    live_review,
)
from tests.storage.test_holding_reviews import ACCOUNT, review


def raw_regime(conn: sqlite3.Connection, raw: str) -> None:
    conn.execute("UPDATE regime_snapshots SET raw_regime=?", (raw,))
    conn.commit()


def test_crisis_mode_turns_off_swaps_and_bans_floors_on_sales(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path, FULLY_INVESTED)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["MU"]["episode_id"]
    floored = decision("", "MU", "TRIM", 0.5).model_copy(update={"entry_price_min": 70.0})
    output = AuthoredOutput(
        decisions=[floored],
        thesis_reviews=[complete_review(episode, "MU", 73)],
        candidates_considered=[amd_clears_the_bar()],
        public_summary="x",
    )

    calm_swap = unanswered_challengers(conn, run, output)
    crisis_swap = unanswered_challengers(conn, run, output, crisis=True)
    crisis_floor = unreviewed_holdings(conn, run, output, crisis=True)

    assert calm_swap and "cash can't fund it" in calm_swap
    assert crisis_swap is None
    # A floor is lifted by the worker, never a reason to send the review back.
    assert crisis_floor is None or "entry_price_min" not in crisis_floor
    conn.close()


def test_the_worker_lifts_a_floor_from_a_protective_exit_instead_of_retrying(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path, FULLY_INVESTED)
    save_run(conn, run)
    episodes = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)
    calls: list[str] = []

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        calls.append(prompt)
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        return AuthoredOutput(
            decisions=[
                decision(namespace, "MU", "SELL", 0.0).model_copy(update={"entry_price_min": 70.0})
            ],
            thesis_reviews=[
                complete_review(episodes["NVDA"]["episode_id"]),
                complete_review(episodes["MU"]["episode_id"], "MU", 73).model_copy(
                    update={"state": "invalidated"}
                ),
            ],
            public_summary="Sold MU.",
        )

    execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY,
        log_root=tmp_path / "logs",
    )

    floors = conn.execute(
        "SELECT json_extract(record_json, '$.entry_price_min') FROM decision_records "
        "WHERE ticker='MU'"
    ).fetchall()
    assert floors == [(None,)]
    assert len(calls) == 1
    conn.close()


def test_a_retry_amends_the_first_answer_and_never_replaces_a_better_one(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    save_run(conn, run)
    prompts: list[str] = []

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        prompts.append(prompt)
        first = len(prompts) == 1
        events(kwargs["log_dir"], opens=5 if first else 0)
        return AuthoredOutput(
            candidates_considered=[candidate(ticker) for ticker in ("AMD", "TSM", "LRCX")]
            if first
            else [candidate("AMD")],
            public_summary="First pass." if first else "Second pass.",
        )

    attempt = execute_attempt(
        conn,
        run.run_id,
        "review-model",
        profile=_profile(),
        runner=author,
        clock=lambda: WEDNESDAY_MIDDAY,
        log_root=tmp_path / "logs",
        hunt_minimum=3,
    )

    research = json.loads((tmp_path / "logs" / attempt.attempt_id / "research.json").read_text())
    assert "Correct only these problems" in prompts[1]
    assert "YOUR PREVIOUS ANSWER:" in prompts[1] and "First pass." in prompts[1]
    assert {"kept_first_pass": True} in research["passes"]
    assert (attempt.status, attempt.public_summary) == ("no_action", "First pass.")
    conn.close()


def test_exposure_above_the_band_or_before_the_weekend_needs_an_answer(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path, FULLY_INVESTED)
    friday_preclose = run.model_copy(update={"slot": "preclose"})
    friday = WEDNESDAY_MIDDAY + timedelta(days=2, hours=2)

    def gap(target: RuntimeRun, **output: Any) -> str | None:
        return unanswered_exposure(
            conn, target, AuthoredOutput(public_summary="x", **output), now=WEDNESDAY_MIDDAY
        )

    in_band = gap(run)
    raw_regime(conn, "YELLOW")
    unanswered = gap(run)
    held = gap(
        run, exposure_decision=AuthoredExposureDecision(action="hold", reasoning="Theses intact.")
    )
    empty_reduce = gap(
        run, exposure_decision=AuthoredExposureDecision(action="reduce", reasoning="Trim beta.")
    )
    raw_regime(conn, "GREEN")
    weekend = unanswered_exposure(
        conn, friday_preclose, AuthoredOutput(public_summary="x"), now=friday
    )

    assert in_band is None
    assert unanswered and "exposure is 96.0% against the GREEN band" in unanswered
    assert held is None
    assert empty_reduce and "records no SELL or TRIM" in empty_reduce
    assert weekend and "last review before the weekend" in weekend
    conn.close()


def test_a_move_blamed_on_the_market_must_be_shown_to_be_the_markets(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path).model_copy(
        update={"prepared_at": WEDNESDAY_MIDDAY + timedelta(minutes=5)}
    )
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    # NVDA trades at $230, under the $240 invalidation price this review stated.
    review(conn, episode, "NVDA", WEDNESDAY_MIDDAY, prices=(300, 340, 240))
    restated = complete_review(episode).model_copy(
        update={
            "realization_price_low": 300.0,
            "realization_price_high": 340.0,
            "invalidation_price": 220.0,
            "range_change_evidence": "The whole market fell.",
        }
    )

    def gap(**update: Any) -> str:
        return (
            unreviewed_holdings(
                conn,
                run,
                AuthoredOutput(
                    thesis_reviews=[restated.model_copy(update=update)], public_summary="x"
                ),
            )
            or ""
        )

    unattributed = gap()
    blamed_on_market = gap(move_attribution="market")

    assert "say in move_attribution" in unattributed
    assert "without data to show the market explains it" in blamed_on_market
    conn.close()


def test_a_crisis_review_whose_refresh_fails_still_runs_but_only_sells(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    run = live_review(conn, tmp_path)
    save_run(conn, run)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    prompts: list[str] = []
    attempts: list[object] = []

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        prompts.append(prompt)
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        return AuthoredOutput(
            decisions=[decision(namespace, "AMD", "BUY", 0.12)],
            thesis_reviews=[complete_review(episode)],
            candidates_considered=[amd_clears_the_bar()],
            public_summary="Bought AMD.",
        )

    def broken() -> object:
        raise BrokerSessionFailure("robinhood unavailable")

    def attempt() -> Any:
        return execute_attempt(
            conn,
            run.run_id,
            "review-model",
            profile=_profile(),
            runner=author,
            clock=lambda: WEDNESDAY_MIDDAY,
            log_root=tmp_path / "logs",
            snapshot_collector=broken,
            retry=bool(attempts),
        )

    calm = attempt()
    attempts.append(calm)
    raw_regime(conn, "YELLOW")
    crisis = attempt()

    assert (calm.status, calm.reason) == ("blocked", "snapshot_stale")
    assert crisis.status == "no_action"
    assert "The account refresh failed" in prompts[-1]
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 0
    conn.close()


def test_only_the_morning_and_midday_reviews_must_hunt(tmp_path: Path) -> None:
    def run_slot(slot: str) -> Any:
        folder = tmp_path / slot
        folder.mkdir()
        conn = connect(folder / "boustrategy.db")
        run = live_review(conn, folder, slot=slot)
        save_run(conn, run)
        episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
        attempt = execute_attempt(
            conn,
            run.run_id,
            "review-model",
            profile=_profile(),
            runner=lambda prompt, **kwargs: AuthoredOutput(
                thesis_reviews=[complete_review(episode)], public_summary="Holdings only."
            ),
            clock=lambda: WEDNESDAY_MIDDAY,
            log_root=folder / "logs",
            hunt_minimum=3,
        )
        conn.close()
        return attempt

    preclose, midday = run_slot("preclose"), run_slot("midday")

    assert preclose.status == "no_action"
    assert (midday.status, midday.reason) == ("failed", "insufficient_research")


def test_an_event_review_starts_on_an_urgent_cause_away_from_scheduled_slots(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    live_review(conn, tmp_path)
    episode = live_holding_episodes(conn, ACCOUNT, WEDNESDAY_MIDDAY)["NVDA"]["episode_id"]
    review(conn, episode, "NVDA", WEDNESDAY_MIDDAY, prices=(300, 340, 240))
    conn.commit()
    snapshot_id = conn.execute(
        "SELECT portfolio_snapshot_id FROM live_portfolio_snapshots"
    ).fetchone()
    snapshot = get_live_portfolio_snapshot(conn, snapshot_id[0])
    assert snapshot is not None
    near_preclose = WEDNESDAY_MIDDAY + timedelta(hours=1, minutes=45)
    mid_afternoon = WEDNESDAY_MIDDAY + timedelta(hours=1)

    quiet = event_review_cause(conn, snapshot, near_preclose)
    cause = event_review_cause(conn, snapshot, mid_afternoon)
    insert_trigger(
        conn,
        "event_review",
        "NVDA:below_invalidation_price",
        mid_afternoon.date(),
        mid_afternoon.date(),
        {},
    )
    repeated = event_review_cause(conn, snapshot, mid_afternoon)

    assert quiet is None
    assert cause == "NVDA:below_invalidation_price"
    assert repeated is None
    conn.close()
