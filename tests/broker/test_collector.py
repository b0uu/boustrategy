import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.broker.collector import (
    AccountObservation,
    QuoteObservation,
    collect_preflight,
    collect_snapshot,
    snapshot_prompt,
)
from app.schemas.live_execution import ExecutionProfile
from app.storage.database import connect
from app.storage.records import get_live_portfolio_snapshot

FINGERPRINT = "f00dfeedcafe0001"


def _profile() -> ExecutionProfile:
    return ExecutionProfile(
        execution_profile_id="codex",
        agent_provider="CODEX",
        account_alias="codex-agentic",
        broker_account_fingerprint=FINGERPRINT,
        enabled=True,
        max_order_notional=20,
        max_quote_age_seconds=60,
        max_spread_bps=50,
    )


def _session(payload: dict[str, Any], seen: dict[str, Any]) -> Any:
    def session(prompt: str, *, schema: Any, **kwargs: Any) -> Any:
        seen["prompt"] = prompt
        seen["schema"] = schema
        seen["kwargs"] = kwargs
        return schema.model_validate(payload)

    return session


def test_collect_snapshot_saves_fingerprint_checked_snapshot_with_themes(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    conn.execute(
        "INSERT INTO decision_records (decision_id, created_at, ticker, decision, record_json) "
        "VALUES ('d1', '2026-09-01T00:00:00+00:00', 'NVDA', 'BUY', ?)",
        (json.dumps({"primary_theme_id": "ai_semiconductors"}),),
    )
    conn.commit()
    seen: dict[str, Any] = {}
    now = datetime(2026, 9, 10, 22, 5, tzinfo=UTC)
    payload = {
        "broker_account_fingerprint": FINGERPRINT,
        "account_number_last4": "0001",
        "account_equity": 118.5,
        "buying_power": 80.25,
        "cash": 80.25,
        "positions": [
            {
                "ticker": "NVDA",
                "market_value": 38.25,
                "quantity": 0.2,
                "average_cost": 180.0,
                "price": 191.25,
                "quote_at": "2026-09-10T18:04:00+00:00",
            },
            {"ticker": "TSM", "market_value": 0.0, "quantity": 0.0},
        ],
        "broker_reported_at": "",
    }

    snapshot = collect_snapshot(
        conn,
        _profile(),
        now=now,
        session=_session(payload, seen),
        codex_home=tmp_path,
        log_dir=tmp_path / "logs",
    )

    stored = get_live_portfolio_snapshot(conn, snapshot.portfolio_snapshot_id)
    assert stored == snapshot
    assert snapshot.portfolio_snapshot_id == "snap_codex_20260910T220500000000Z"
    assert snapshot.captured_at == now and snapshot.account_equity == 118.5
    assert [(p.ticker, p.market_value, p.primary_theme_id) for p in snapshot.positions] == [
        ("NVDA", 38.25, "ai_semiconductors")
    ]
    reporting = snapshot.reporting
    assert reporting is not None
    assert reporting.complete is True
    assert reporting.cash == Decimal("80.25") and reporting.equity == Decimal("118.50")
    assert [
        (p.ticker, str(p.market_value), p.price_quality) for p in reporting.positions or []
    ] == [("NVDA", "38.25", "current")]
    assert seen["schema"] is AccountObservation
    assert FINGERPRINT in seen["prompt"] and "Never print a full account number" in seen["prompt"]
    assert str(seen["kwargs"]["log_path"]).endswith("snapshot-codex-20260910T220500000000Z.log")
    conn.close()


def test_collect_snapshot_rejects_other_accounts_and_unknown_theme_defaults(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    other = {
        "broker_account_fingerprint": "3b54aab2d5d5694f",
        "account_number_last4": "9001",
        "account_equity": 2700.0,
        "buying_power": 1500.0,
        "positions": [],
        "broker_reported_at": "",
    }

    with pytest.raises(ValueError, match="collector_account_mismatch"):
        collect_snapshot(conn, _profile(), session=_session(other, {}), codex_home=tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM live_portfolio_snapshots").fetchone()[0] == 0

    unknown = {
        **other,
        "broker_account_fingerprint": FINGERPRINT,
        "positions": [{"ticker": "AAPL", "market_value": 10.0, "quantity": 0.05}],
    }
    snapshot = collect_snapshot(
        conn, _profile(), session=_session(unknown, {}), codex_home=tmp_path
    )
    assert snapshot.positions[0].primary_theme_id == "unclassified"
    conn.close()


def test_collect_preflight_maps_quote_observation(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    payload = {
        "broker_account_fingerprint": FINGERPRINT,
        "ticker": "nvda",
        "bid": 181.10,
        "ask": 181.16,
        "quote_at": "2026-09-10T13:31:05-04:00",
        "tradable": True,
        "fractionable": True,
        "regular_market_hours": True,
        "account_equity": 100.0,
        "buying_power": 100.0,
        "current_position_value": 0.0,
    }

    preflight = collect_preflight(
        _profile(), "NVDA", session=_session(payload, seen), codex_home=tmp_path
    )

    assert preflight.ticker == "NVDA" and preflight.bid == 181.10 and preflight.ask == 181.16
    assert preflight.quote_at.isoformat() == "2026-09-10T13:31:05-04:00"
    assert preflight.broker_account_fingerprint == FINGERPRINT
    assert seen["schema"] is QuoteObservation
    with pytest.raises(ValueError, match="collector_ticker_mismatch"):
        collect_preflight(_profile(), "TSM", session=_session(payload, {}), codex_home=tmp_path)


def test_snapshot_prompt_forbids_order_tools() -> None:
    prompt = snapshot_prompt(_profile())

    assert "Never call any tool that reviews, places, modifies or cancels an order" in prompt
    assert "get_portfolio" in prompt and "get_equity_positions" in prompt


def test_valuation_is_incomplete_when_a_quote_or_cash_is_missing(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    unpriced = {
        "broker_account_fingerprint": FINGERPRINT,
        "account_number_last4": "0001",
        "account_equity": 118.5,
        "buying_power": 80.25,
        "cash": 80.25,
        "positions": [{"ticker": "NVDA", "market_value": 38.25, "quantity": 0.2}],
        "broker_reported_at": None,
    }

    snapshot = collect_snapshot(
        conn, _profile(), session=_session(unpriced, {}), codex_home=tmp_path
    )

    reporting = snapshot.reporting
    assert reporting is not None
    assert reporting.complete is False
    assert reporting.positions is not None
    assert reporting.positions[0].price_quality == "missing"
    conn.close()


def test_valuation_after_the_close_is_recorded_as_a_session_close(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    payload = {
        "broker_account_fingerprint": FINGERPRINT,
        "account_number_last4": "0001",
        "account_equity": 100.0,
        "buying_power": 100.0,
        "cash": 100.0,
        "positions": [],
        "broker_reported_at": None,
    }

    snapshot = collect_snapshot(
        conn,
        _profile(),
        now=datetime(2026, 9, 10, 22, 10, tzinfo=UTC),
        session=_session(payload, {}),
        codex_home=tmp_path,
    )

    reporting = snapshot.reporting
    assert reporting is not None
    assert reporting.phase == "session_close"
    assert reporting.session_date is not None and reporting.session_date.isoformat() == "2026-09-10"
    assert reporting.previous_session_date is not None
    assert reporting.complete is True
    conn.close()
