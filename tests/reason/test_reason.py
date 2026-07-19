import json
import sys
from datetime import date
from pathlib import Path

import pytest

from app.policy.decision_policy import PortfolioContext
from app.reason.intake import build_intake
from app.reason.run import main, submit_decision
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
    assert "RULES NOT YET SIGNED OFF" in bundle
    assert "Headline 2026-06-10" in bundle
    assert json.loads((tmp_path / "out" / "portfolio.json").read_text())["equity"] == 101_120
    assert json.loads((tmp_path / "out" / "triggers.json").read_text())[0]["subject"] == "NVDA"


def test_intake_hides_regime_banner_after_signoff(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.db")

    bundle = build_intake(
        conn, date(2026, 6, 10), tmp_path / "out", rules_signed_off=True
    ).read_text(encoding="utf-8")

    assert "RULES NOT YET SIGNED OFF" not in bundle


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
        conn: object, record: object, portfolio: PortfolioContext, true_regime_state: object
    ) -> ProcessOutcome:
        captured["portfolio"] = portfolio
        return ProcessOutcome(decision_id=None, final_status=DecisionStatus.SCHEMA_FAILED)

    def fake_regime(conn: object, on_date: date) -> None:
        return None

    monkeypatch.setattr("app.reason.run.portfolio_context", fake_context)
    monkeypatch.setattr("app.reason.run.process_decision", fake_process)
    monkeypatch.setattr("app.reason.run.latest_published_regime", fake_regime)

    submit_decision(object(), {"ticker": "nvda"}, date(2026, 6, 10))  # type: ignore[arg-type]

    assert captured == {"ticker": "nvda", "portfolio": expected_portfolio}


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
