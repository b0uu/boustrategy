import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.policy.decision_policy import PortfolioContext
from app.reason.intake import build_intake
from app.reason.run import main, prepare_session, submit_decision
from app.regime.rules import Component, RegimeScore
from app.schemas.decision_record import RegimeState
from app.schemas.order_intent import ExecutionMode
from app.state.pipeline import DecisionStatus, ProcessOutcome
from app.storage.database import connect
from app.triggers.store import insert_trigger
from tests.fixtures.decision_records import valid_decision_record_data


def test_intake_renders_every_section_and_does_not_mutate_database(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    conn.execute(
        """
        INSERT INTO regime_snapshots VALUES
        ('2026-06-10', 'GREEN', 'GREEN', 3, '{"trend": 1}', '2026-06-10T10:00:00Z')
        """
    )
    insert_trigger(
        conn, "price_move", "NVDA", date(2026, 6, 10), date(2026, 6, 10), {"move": "large"}
    )
    conn.execute(
        """
        INSERT INTO x_posts (post_id, handle, posted_at, text, url, fetched_at)
        VALUES ('post-1', 'analyst', '2026-06-10', 'Long-form item',
                'https://example.com/post-1', '2026-06-10')
        """
    )
    conn.execute("INSERT INTO x_article_queue (post_id, queued_at) VALUES ('post-1', '2026-06-10')")
    conn.execute(
        """
        INSERT INTO paper_positions VALUES
        ('NVDA', 10, 100, '2026-06-01', 'ai_semiconductors')
        """
    )
    conn.execute(
        """
        INSERT INTO daily_prices VALUES
        ('NVDA', '2026-06-10', 110, 115, 108, 112, 112, 1000, 'test', '2026-06-10')
        """
    )
    conn.execute(
        """
        INSERT INTO calendar_events VALUES
        ('earnings', 'NVDA', '2026-06-12', 'estimated', 'test', '2026-06-10')
        """
    )
    conn.commit()
    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    for day in ("2026-06-08", "2026-06-09", "2026-06-10"):
        (digest_dir / f"{day}.md").write_text(
            f"# {day}\n\n## Actionable\n\n- Headline {day}\n\n## Other\n", encoding="utf-8"
        )
    before = "\n".join(conn.iterdump())

    bundle_path = build_intake(conn, date(2026, 6, 10), tmp_path / "out", digest_dir)

    assert "\n".join(conn.iterdump()) == before
    bundle = bundle_path.read_text(encoding="utf-8")
    for section in (
        "## Regime",
        "## Pending triggers",
        "## Recent daily digests",
        "## Pending article queue",
        "## Paper portfolio",
        "## Today's intake quota state",
        "## Upcoming calendar (7 days)",
        "## Required runtime reading",
    ):
        assert section in bundle
    assert "RULES NOT YET SIGNED OFF" not in bundle
    assert "Headline 2026-06-10" in bundle
    assert json.loads((tmp_path / "out" / "portfolio.json").read_text())["equity"] == 6_120
    assert json.loads((tmp_path / "out" / "triggers.json").read_text())[0]["subject"] == "NVDA"


def test_intake_shows_regime_banner_before_signoff(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")

    bundle = build_intake(
        conn, date(2026, 6, 10), tmp_path / "out", rules_signed_off=False
    ).read_text(encoding="utf-8")

    assert "RULES NOT YET SIGNED OFF" in bundle


def test_intake_excludes_nonpending_and_future_queue_items(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    for post_id in ("current", "resolved", "future"):
        conn.execute(
            """
            INSERT INTO x_posts (post_id, handle, posted_at, text, url, fetched_at)
            VALUES (?, 'analyst', '2026-06-10', ?, ?, '2026-06-10')
            """,
            (post_id, post_id, f"https://example.com/{post_id}"),
        )
    conn.executemany(
        "INSERT INTO x_article_queue (post_id, queued_at, status) VALUES (?, ?, ?)",
        [
            ("current", "2026-06-10T10:00:00Z", "pending"),
            ("resolved", "2026-06-10T10:00:00Z", "summarized"),
            ("future", "2026-06-11T10:00:00Z", "pending"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO trigger_events
            (trigger_id, trigger_type, subject, fired_at, details_json, status)
        VALUES (?, 'manual', ?, ?, '{}', ?)
        """,
        [
            ("current", "CURRENT", "2026-06-10", "pending"),
            ("consumed", "CONSUMED", "2026-06-10", "consumed"),
            ("future", "FUTURE", "2026-06-11", "pending"),
        ],
    )
    conn.commit()

    build_intake(conn, date(2026, 6, 10), tmp_path / "out")

    articles = (tmp_path / "out" / "bundle.md").read_text(encoding="utf-8")
    triggers = json.loads((tmp_path / "out" / "triggers.json").read_text(encoding="utf-8"))
    assert "https://example.com/current" in articles
    assert "https://example.com/resolved" not in articles
    assert "https://example.com/future" not in articles
    assert [item["trigger_id"] for item in triggers] == ["current"]


def test_prepare_requires_completed_same_day_digest_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path / "test.db")
    refreshed = False

    def fake_refresh(*args: object, **kwargs: object) -> int:
        nonlocal refreshed
        refreshed = True
        return 0

    monkeypatch.setattr("app.reason.run.refresh_ticker", fake_refresh)

    with pytest.raises(FileNotFoundError, match="missing same-day digest"):
        prepare_session(
            conn,
            date(2026, 6, 10),
            tmp_path / "out",
            digest_dir=tmp_path / "digests",
            watchlist_path=tmp_path / "watchlist.md",
        )

    assert refreshed is False


def test_prepare_refreshes_pending_intents_and_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(tmp_path / "test.db")
    target = date(2026, 6, 10)
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, finished_at, status)
        VALUES ('2026-06-10-morning', 'morning', '2026-06-10', '2026-06-10', 'digested')
        """
    )
    conn.execute(
        """
        INSERT INTO order_intents
            (order_intent_id, decision_id, created_at, ticker, side, intent_json)
        VALUES ('oi_pending', 'dec_pending', '2026-04-01T12:00:00Z', 'AMD', 'BUY', '{}')
        """
    )
    conn.commit()
    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    (digest_dir / "2026-06-10.md").write_text("# digest\n", encoding="utf-8")
    watchlist = tmp_path / "watchlist.md"
    watchlist.write_text("- NVDA \N{EM DASH} approved\n", encoding="utf-8")
    refreshed: dict[str, tuple[date, date]] = {}

    def fake_refresh(conn: object, ticker: str, start: date, end: date) -> int:
        refreshed[ticker] = (start, end)
        return 2

    def fake_build(
        conn: object,
        on_date: date,
        out_dir: str | Path,
        digest_dir: str | Path,
    ) -> Path:
        path = Path(out_dir) / "bundle.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# bundle\n", encoding="utf-8")
        return path

    score = RegimeScore(RegimeState.GREEN, 4, {"test": Component(1.0, 4)})
    monkeypatch.setattr("app.reason.run.refresh_ticker", fake_refresh)
    monkeypatch.setattr("app.reason.run.settle", lambda conn, through_date: (1, 0))
    monkeypatch.setattr("app.reason.run.refresh_earnings", lambda conn, ticker, today: 1)
    monkeypatch.setattr("app.reason.run.sync_fomc", lambda conn, through: 8)
    monkeypatch.setattr(
        "app.reason.run.evaluate_triggers", lambda conn, tickers, on_date: {"price_move": 1}
    )
    monkeypatch.setattr(
        "app.reason.run.score_date", lambda conn, on_date: (RegimeState.GREEN, score)
    )
    monkeypatch.setattr("app.reason.run.build_intake", fake_build)

    result = prepare_session(
        conn,
        target,
        tmp_path / "out",
        digest_dir=digest_dir,
        watchlist_path=watchlist,
    )

    assert set(refreshed) == {"AMD", "NVDA", "QQQ", "SPY"}
    assert refreshed["AMD"][0] == date(2026, 3, 25)
    assert result.fills_created == 1
    assert result.completed_digest_runs == ["2026-06-10-morning"]
    receipt = json.loads((tmp_path / "out" / "preparation.json").read_text(encoding="utf-8"))
    assert receipt["bundle_path"].endswith("bundle.md")


@pytest.mark.parametrize(
    ("kind", "expected_status", "consumed"),
    [
        ("approved", DecisionStatus.ORDER_INTENT_CREATED, True),
        ("rejected", DecisionStatus.POLICY_REJECTED, True),
        ("schema_failed", DecisionStatus.SCHEMA_FAILED, False),
    ],
)
def test_submit_trigger_consumption_matrix(
    tmp_path: Path, kind: str, expected_status: DecisionStatus, consumed: bool
) -> None:
    conn = connect(tmp_path / f"{kind}.db")
    trigger = "manual:NVDA:2026-06-10"
    insert_trigger(conn, "manual", "NVDA", date(2026, 6, 10), date(2026, 6, 10), {})
    record = valid_decision_record_data()
    if kind == "rejected":
        record["proposed_target_weight"] = 0.3
        record["final_target_weight"] = 0.3
    elif kind == "schema_failed":
        record.pop("ticker")

    outcome = submit_decision(conn, record, date(2026, 6, 10), [trigger])

    assert outcome.final_status == expected_status
    status = conn.execute(
        "SELECT status FROM trigger_events WHERE trigger_id = ?", (trigger,)
    ).fetchone()[0]
    assert status == ("consumed" if consumed else "pending")


def test_intake_extracts_headlines_from_a_real_rendered_digest(tmp_path: Path) -> None:
    from app.x.accounts import Account, upsert_account
    from app.x.pipeline import render_digest
    from app.x.posts import XPost, insert_new_posts

    conn = connect(tmp_path / "test.db")
    now = datetime.now(UTC)
    upsert_account(conn, Account(handle="analyst", user_id="1"))
    insert_new_posts(
        conn,
        [
            XPost(
                post_id="1",
                handle="analyst",
                posted_at=now,
                text="CoWoS capacity\noversubscribed through 2027",
                url="https://x.com/analyst/status/1",
                fetched_at=now,
            )
        ],
    )
    conn.execute(
        """
        INSERT INTO x_runs (run_id, slot, started_at, finished_at, status)
        VALUES ('2026-06-10-morning', 'morning', ?, ?, 'routed')
        """,
        (now.isoformat(), now.isoformat()),
    )
    conn.execute(
        """
        INSERT INTO x_route_decisions
            (post_id, run_id, route, rank, reason, predictor, decided_at)
        VALUES ('1', '2026-06-10-morning', 'digest', 'headline', 'supply signal', 'judge', ?)
        """,
        (now.isoformat(),),
    )
    conn.commit()
    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    render_digest(conn, date(2026, 6, 10), digest_dir / "2026-06-10.md")

    bundle_path = build_intake(conn, date(2026, 6, 10), tmp_path / "out", digest_dir)

    bundle = bundle_path.read_text(encoding="utf-8")
    assert (
        "CoWoS capacity oversubscribed through 2027 | supply signal | "
        "https://x.com/analyst/status/1"
    ) in bundle
    assert "No ACTIONABLE headline items." not in bundle


def test_submit_rejects_self_reported_regime_mismatch(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    conn.execute(
        """
        INSERT INTO regime_snapshots VALUES
        ('2026-06-10', 'RED', 'RED', -5, '{"trend": -1}', '2026-06-10T10:00:00Z')
        """
    )
    record = valid_decision_record_data()  # fixture's regime_state defaults to GREEN

    outcome = submit_decision(conn, record, date(2026, 6, 10))

    assert outcome.final_status == DecisionStatus.POLICY_REJECTED
    assert "regime_state_mismatch" in outcome.policy_reasons


def test_submit_uses_latest_snapshot_on_or_before_the_submit_date(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")
    conn.execute(
        """
        INSERT INTO regime_snapshots VALUES
        ('2026-06-01', 'GREEN', 'GREEN', 5, '{"trend": 1}', '2026-06-01T10:00:00Z')
        """
    )
    record = valid_decision_record_data()  # regime_state GREEN matches the only snapshot

    outcome = submit_decision(conn, record, date(2026, 6, 10))

    assert outcome.final_status == DecisionStatus.ORDER_INTENT_CREATED
    assert "regime_state_mismatch" not in outcome.policy_reasons


def test_submit_passes_record_ticker_to_portfolio_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    expected_portfolio = PortfolioContext(
        holdings_count=0, buy_add_trades_today=0, sell_trim_trades_today=0
    )

    def fake_context(
        conn: object, on_date: date, exclude_ticker: str | None = None
    ) -> PortfolioContext:
        captured["ticker"] = exclude_ticker
        return expected_portfolio

    def fake_process(
        conn: object,
        record: object,
        portfolio: PortfolioContext,
        true_regime_state: object,
        *,
        execution_mode: ExecutionMode,
        execution_profile_id: str,
    ) -> ProcessOutcome:
        captured["portfolio"] = portfolio
        captured["execution_mode"] = execution_mode
        captured["execution_profile_id"] = execution_profile_id
        return ProcessOutcome(decision_id=None, final_status=DecisionStatus.SCHEMA_FAILED)

    def fake_regime(conn: object, on_date: date) -> None:
        return None

    monkeypatch.setattr("app.reason.run.portfolio_context", fake_context)
    monkeypatch.setattr("app.reason.run.process_decision", fake_process)
    monkeypatch.setattr("app.reason.run.latest_published_regime", fake_regime)

    submit_decision(object(), {"ticker": "nvda"}, date(2026, 6, 10))  # type: ignore[arg-type]

    assert captured == {
        "ticker": "nvda",
        "portfolio": expected_portfolio,
        "execution_mode": ExecutionMode.PAPER,
        "execution_profile_id": "",
    }


def test_submit_cli_prints_full_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    input_path = tmp_path / "decision.json"
    record = valid_decision_record_data()
    input_path.write_text(json.dumps(record, default=str), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.reason.run",
            "--db",
            str(tmp_path / "test.db"),
            "submit",
            "--in",
            str(input_path),
            "--date",
            "2026-06-10",
        ],
    )

    main()

    outcome = json.loads(capsys.readouterr().out)
    assert outcome["final_status"] == "order_intent_created"
    assert outcome["policy_reasons"] == []
    assert outcome["order_intent_id"] == "oi_dec_001"
