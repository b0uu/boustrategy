import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.reason.codex_runner import research_activity, run_codex
from app.reason.worker import HUNT_MINIMUM, execute_attempt, hunt_shortfall
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.runtime import AuthoredOutput, CandidateConsidered
from app.storage.database import connect
from tests.fixtures.decision_records import valid_decision_record_data
from tests.reason.test_runtime import paper_run

NOW = datetime(2026, 6, 10, 21, 45, tzinfo=UTC)


def events(folder: Path, *, searches: int = 0, opens: int = 0, reasoning: int = 0) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, Any]] = [{"type": "thread.started"}]
    for index in range(searches):
        lines.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "web_search",
                    "action": {"type": "search", "queries": [f"q{index}"]},
                },
            }
        )
    for _ in range(opens):
        lines.append(
            {"type": "item.started", "item": {"type": "web_search", "action": {"type": "other"}}}
        )
        lines.append(
            {"type": "item.completed", "item": {"type": "web_search", "action": {"type": "other"}}}
        )
    lines.append(
        {
            "type": "turn.completed",
            "usage": {"reasoning_output_tokens": reasoning, "output_tokens": 50},
        }
    )
    (folder / "events.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines), encoding="utf-8"
    )


def candidate(
    ticker: str, outcome: str = "PASS", url: str = "https://investor.example.com/q2"
) -> CandidateConsidered:
    return CandidateConsidered.model_validate(
        {
            "ticker": ticker,
            "idea_source": "digest headline",
            "sources_opened": [url] if url else [],
            "outcome": outcome,
            "reason": "Primary filing did not confirm the claimed demand inflection.",
        }
    )


HUNTED = AuthoredOutput(
    candidates_considered=[candidate("NVDA", "WATCHLIST"), candidate("TSM"), candidate("MSFT")],
    public_summary="Researched three candidates; none cleared the bar today.",
)


def test_research_activity_counts_searches_opens_and_tokens(tmp_path: Path) -> None:
    events(tmp_path, searches=2, opens=4, reasoning=811)

    assert research_activity(tmp_path) == {
        "searches": 2,
        "opens": 4,
        "reasoning_tokens": 811,
        "output_tokens": 50,
    }
    assert research_activity(tmp_path / "missing")["opens"] == 0


def test_hunt_shortfall_names_each_missing_piece() -> None:
    enough = {"opens": 3}

    assert hunt_shortfall(HUNTED, enough, 3) is None
    assert hunt_shortfall(AuthoredOutput(public_summary="No action."), {"opens": 0}, 0) is None

    empty = hunt_shortfall(AuthoredOutput(public_summary="No action."), {"opens": 0}, 3)
    assert empty is not None
    assert "0 distinct candidates" in empty and "0 pages were opened" in empty

    snippets = AuthoredOutput(
        candidates_considered=[candidate("NVDA"), candidate("TSM", url=""), candidate("NVDA")],
        public_summary="Thin.",
    )
    thin = hunt_shortfall(snippets, enough, 3)
    assert thin is not None and "2 distinct" in thin and "for TSM" in thin

    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data())
    unledgered = hunt_shortfall(HUNTED.model_copy(update={"decisions": [record]}), enough, 3)
    assert unledgered is not None and f"{record.ticker} is not recorded" in unledgered


def test_production_runner_enforces_the_hunt_by_default(tmp_path: Path, monkeypatch: Any) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)

    def lazy(prompt: str, **kwargs: Any) -> AuthoredOutput:
        return AuthoredOutput(public_summary="No action.")

    # An injected test runner is exempt unless it opts in, so existing fakes keep working.
    exempt = execute_attempt(
        conn, run.run_id, "m", log_root=tmp_path / "logs", runner=lazy, clock=lambda: NOW
    )
    assert exempt.status == "no_action"

    # The production runner is enforced without anyone passing hunt_minimum.
    assert (execute_attempt.__kwdefaults__ or {})["runner"] is run_codex
    monkeypatch.setattr("app.reason.worker.run_codex", lazy)
    (tmp_path / "second").mkdir()
    second = paper_run(conn, tmp_path / "second", run_id="research-enforced")
    enforced = execute_attempt(
        conn,
        second.run_id,
        "m",
        log_root=tmp_path / "logs",
        runner=lazy,
        clock=lambda: NOW,
    )
    assert (enforced.status, enforced.reason) == ("failed", "insufficient_research")
    assert HUNT_MINIMUM == 3
    conn.close()


def test_a_skipped_hunt_is_retried_once_with_the_reason(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)
    prompts: list[str] = []

    def author(prompt: str, **kwargs: Any) -> AuthoredOutput:
        prompts.append(prompt)
        log_dir: Path = kwargs["log_dir"]
        if len(prompts) == 1:
            events(log_dir, searches=1, reasoning=174)
            return AuthoredOutput(public_summary="No action.")
        events(log_dir, searches=4, opens=6, reasoning=2400)
        return HUNTED

    attempt = execute_attempt(
        conn,
        run.run_id,
        "m",
        log_root=tmp_path / "logs",
        runner=author,
        clock=lambda: NOW,
        hunt_minimum=3,
    )

    assert attempt.status == "no_action"
    assert len(prompts) == 2
    assert "REJECTED BY THE TRUSTED WORKER" in prompts[1] and "0 distinct candidates" in prompts[1]
    research = json.loads(
        (tmp_path / "logs" / attempt.attempt_id / "research.json").read_text(encoding="utf-8")
    )
    assert [item["activity"]["opens"] for item in research["passes"]] == [0, 6]
    assert research["passes"][1]["shortfall"] is None
    assert [item["ticker"] for item in research["candidates"]] == ["NVDA", "TSM", "MSFT"]
    assert (tmp_path / "logs" / attempt.attempt_id / "second-pass" / "events.jsonl").is_file()
    conn.close()


def test_a_review_that_never_hunts_fails_loudly_and_submits_nothing(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)
    calls = 0

    def stubborn(prompt: str, **kwargs: Any) -> AuthoredOutput:
        nonlocal calls
        calls += 1
        namespace = prompt.split("Decision namespace: ")[1].splitlines()[0]
        record = InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "decision_id": namespace + "x"}
        )
        events(kwargs["log_dir"], opens=5)
        return AuthoredOutput(decisions=[record], public_summary="One unresearched buy.")

    attempt = execute_attempt(
        conn,
        run.run_id,
        "m",
        log_root=tmp_path / "logs",
        runner=stubborn,
        clock=lambda: NOW,
        hunt_minimum=3,
    )

    assert (attempt.status, attempt.reason) == ("failed", "insufficient_research")
    assert calls == 2
    assert conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0] == 0
    conn.close()


def test_no_retry_when_the_time_budget_is_spent(tmp_path: Path, monkeypatch: Any) -> None:
    conn = connect(tmp_path / "source.db")
    run = paper_run(conn, tmp_path)
    ticks = iter([0.0, 1790.0, 1790.0])
    monkeypatch.setattr("app.reason.worker.time", SimpleNamespace(monotonic=lambda: next(ticks)))
    calls = 0

    def slow(prompt: str, **kwargs: Any) -> AuthoredOutput:
        nonlocal calls
        calls += 1
        return AuthoredOutput(public_summary="No action.")

    attempt = execute_attempt(
        conn,
        run.run_id,
        "m",
        log_root=tmp_path / "logs",
        runner=slow,
        clock=lambda: NOW,
        hunt_minimum=3,
        timeout_seconds=1800,
    )

    assert (attempt.status, attempt.reason, calls) == ("failed", "insufficient_research", 1)
    conn.close()


def test_an_actionable_decision_must_carry_the_price_the_review_read() -> None:
    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data())
    ledger = [candidate(record.ticker, str(record.decision)), candidate("TSM"), candidate("MSFT")]
    unpriced = AuthoredOutput(
        decisions=[record], candidates_considered=ledger, public_summary="One buy."
    )

    shortfall = hunt_shortfall(unpriced, {"opens": 3}, 3)
    assert shortfall is not None and "has no reference_price" in shortfall

    priced = unpriced.model_copy(
        update={
            "decisions": [
                record.model_copy(
                    update={
                        "reference_price": 200.0,
                        "reference_price_at": datetime(2026, 9, 11, 19, 0, tzinfo=UTC),
                    }
                )
            ]
        }
    )
    assert hunt_shortfall(priced, {"opens": 3}, 3) is None


def test_a_review_while_the_market_is_closed_puts_ideas_on_the_watchlist() -> None:
    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data()).model_copy(
        update={
            "reference_price": 200.0,
            "reference_price_at": datetime(2026, 9, 11, 22, 15, tzinfo=UTC),
        }
    )
    ledger = [candidate(record.ticker, str(record.decision)), candidate("TSM"), candidate("MSFT")]
    buy = AuthoredOutput(decisions=[record], candidates_considered=ledger, public_summary="Buy.")

    closed = hunt_shortfall(buy, {"opens": 3}, 3, trading_open=False)
    assert closed is not None and "while the market is closed" in closed and "WATCHLIST" in closed
    assert hunt_shortfall(buy, {"opens": 3}, 3, trading_open=True) is None

    watch = [candidate(record.ticker, "WATCHLIST"), candidate("TSM"), candidate("MSFT")]
    researched = AuthoredOutput(candidates_considered=watch, public_summary="Watchlist.")
    assert hunt_shortfall(researched, {"opens": 3}, 3, trading_open=False) is None
