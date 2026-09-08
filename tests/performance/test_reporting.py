from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.performance.calculate import daily_pnl, linked_return
from app.performance.report import materialize
from app.performance.storage import current_observations, ingest
from app.public.publication import publish
from app.public.server import create_public_app
from app.schemas.reporting import (
    OBSERVATION_ADAPTER,
    CoverageObservation,
    FillObservation,
    FlowObservation,
    ReportingPosition,
    ValuationObservation,
)
from app.storage.database import connect

ACCOUNT = "0123456789abcdef"


def common(identity: str, day: int, hour: int = 20) -> dict[str, Any]:
    instant = datetime(2026, 6, day, hour, tzinfo=UTC)
    return {
        "observation_id": identity,
        "external_event_id": identity,
        "mode": "live",
        "account_id": ACCOUNT,
        "occurred_at": instant,
        "recorded_at": instant,
    }


def valuation(identity: str, day: int, equity: str, **changes: Any) -> ValuationObservation:
    data = {
        **common(identity, day),
        "equity": equity,
        "cash": equity,
        "positions": [],
        "complete": True,
        "phase": "session_close",
        "session_date": f"2026-06-{day:02}",
    }
    data.update(changes)
    return ValuationObservation.model_validate(data)


def coverage(day: int = 12) -> CoverageObservation:
    return CoverageObservation(
        **common("coverage", day),
        start_at=datetime(2026, 6, 10, 20, tzinfo=UTC),
        end_at=datetime(2026, 6, day, 20, tzinfo=UTC),
        external_flows_complete=True,
        activity_complete=True,
    )


def flow_facts(
    amount: str = "100", before: str = "110", after: str = "210"
) -> tuple[ValuationObservation, ValuationObservation, FlowObservation]:
    instant = datetime(2026, 6, 11, 15, tzinfo=UTC)
    first = valuation("before", 11, before, occurred_at=instant, phase="before_flow")
    second = valuation("after", 11, after, occurred_at=instant, phase="after_flow")
    flow = FlowObservation(
        **common("flow", 11, 15),
        flow_type="deposit" if Decimal(amount) > 0 else "withdrawal",
        amount=Decimal(amount),
        before_valuation_id="before",
        after_valuation_id="after",
    )
    return first, second, flow


def position(quantity: str, price: str, *, ticker: str = "NVDA") -> ReportingPosition:
    return ReportingPosition(
        ticker=ticker,
        quantity=Decimal(quantity),
        price=Decimal(price),
        market_value=(Decimal(quantity) * Decimal(price)).quantize(Decimal("0.01")),
        quote_at=datetime(2026, 6, 10, 20, tzinfo=UTC),
        price_quality="current",
        asset_class="equity",
    )


def test_linked_growth_around_deposit_is_twenty_one_percent() -> None:
    start, end = valuation("start", 10, "100"), valuation("end", 12, "231")
    before, after, flow = flow_facts()
    result = linked_return(start, end, {"before": before, "after": after}, [flow], [coverage()])
    assert result["return_percent"] == "21.000000"
    assert result["investment_pnl"] == "31.00"
    assert result["net_external_flows"] == "100.00"


@pytest.mark.parametrize(
    ("amount", "before", "after", "end"), [("100", "100", "200", "200"), ("-50", "100", "50", "50")]
)
def test_funding_alone_is_not_investment_return(
    amount: str, before: str, after: str, end: str
) -> None:
    first, second, flow = flow_facts(amount, before, after)
    result = linked_return(
        valuation("start", 10, "100"),
        valuation("end", 12, end),
        {"before": first, "after": second},
        [flow],
        [coverage()],
    )
    assert result["return_percent"] == "0.000000"
    assert result["investment_pnl"] == "0.00"


@pytest.mark.parametrize(
    ("kind", "amount", "end", "expected"),
    [("fee", "2", "98", "-2.000000"), ("dividend", "5", "105", "5.000000")],
)
def test_fees_and_dividends_remain_in_account_return(
    kind: str, amount: str, end: str, expected: str
) -> None:
    action = OBSERVATION_ADAPTER.validate_python(
        {**common(kind, 11), "kind": "corporate_action", "action": kind, "amount": amount}
    )
    result = linked_return(
        valuation("start", 10, "100"), valuation("end", 12, end), {}, [], [coverage()]
    )
    assert action.kind == "corporate_action"
    assert result["return_percent"] == expected


def test_missing_coverage_boundary_and_endpoint_order_are_explicit() -> None:
    start, end = valuation("start", 10, "100"), valuation("end", 12, "231")
    before, after, flow = flow_facts()
    assert linked_return(start, end, {}, [flow], [])["reason"] == "external_flow_coverage_missing"
    assert (
        linked_return(start, end, {}, [flow], [coverage()])["reason"]
        == "external_flow_boundary_missing"
    )
    assert (
        linked_return(before, end, {}, [flow], [coverage()])["reason"]
        == "flow_boundary_endpoint_unsupported"
    )
    assert (
        linked_return(start, before, {}, [flow], [coverage()])["reason"]
        == "flow_boundary_endpoint_unsupported"
    )
    coincident = valuation("coincident", 11, "210", occurred_at=flow.occurred_at)
    assert (
        linked_return(start, coincident, {"before": before, "after": after}, [flow], [coverage()])[
            "reason"
        ]
        == "coincident_flow_endpoint_order_unknown"
    )


def test_reporting_allows_unfunded_but_not_nonfinite_or_false_complete_values() -> None:
    assert valuation("zero", 10, "0").equity == 0
    for value in ("NaN", "Infinity", "0.001"):
        with pytest.raises(ValidationError):
            valuation("invalid", 10, value)
    with pytest.raises(ValidationError, match="does not reconcile"):
        valuation("invalid", 10, "100", cash="99")
    with pytest.raises(ValidationError, match="current position"):
        valuation(
            "stale",
            10,
            "100",
            cash="0",
            positions=[{"ticker": "NVDA", "market_value": "100", "price_quality": "stale"}],
        )


def test_immutable_corrections_are_idempotent_and_cannot_fork_or_change_account(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "source.db")
    original = valuation("original", 10, "100")
    correction = valuation(
        "corrected",
        10,
        "110",
        external_event_id="original",
        supersedes="original",
        recorded_at=datetime(2026, 6, 11, tzinfo=UTC),
    )
    assert ingest(conn, original)
    assert not ingest(conn, original)
    assert ingest(conn, correction)
    assert conn.execute("SELECT COUNT(*) FROM reporting_observations").fetchone()[0] == 2
    assert current_observations(conn, mode="live", account_id=ACCOUNT) == [correction]
    with pytest.raises(ValueError, match="superseded"):
        ingest(conn, correction.model_copy(update={"observation_id": "fork"}))
    with pytest.raises(ValueError, match="cannot change account"):
        ingest(
            conn,
            correction.model_copy(
                update={
                    "observation_id": "other",
                    "supersedes": "corrected",
                    "account_id": "abcdef0123456789",
                }
            ),
        )
    with pytest.raises(ValueError, match="explicit correction"):
        ingest(conn, valuation("duplicate", 10, "100", external_event_id="original"))
    conn.close()


def test_flow_ingestion_checks_account_and_reconciles_boundaries(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    before, after, flow = flow_facts()
    ingest(conn, before)
    ingest(conn, after)
    assert ingest(conn, flow)
    with pytest.raises(ValueError, match="match account"):
        ingest(
            conn,
            flow.model_copy(
                update={
                    "observation_id": "other",
                    "external_event_id": "other",
                    "account_id": "abcdef0123456789",
                }
            ),
        )
    with pytest.raises(ValueError, match="do not reconcile"):
        ingest(
            conn,
            flow.model_copy(
                update={
                    "observation_id": "wrong",
                    "external_event_id": "wrong",
                    "amount": Decimal("101"),
                }
            ),
        )
    conn.close()


def test_daily_pnl_checks_previous_session_and_subtracts_funding() -> None:
    start = valuation("start", 10, "100")
    end = valuation("end", 11, "231", previous_session_date="2026-06-10")
    _, _, flow = flow_facts()
    assert daily_pnl(end, [start, end], [flow], [coverage()])["amount"] == "31"
    assert (
        daily_pnl(valuation("end", 12, "231"), [start], [flow], [coverage()])["reason"]
        == "prior_session_close_missing"
    )


def test_split_and_reopened_holding_episodes_keep_distinct_identity(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    start = valuation("start", 10, "100", cash="0", positions=[position("1", "100")])
    end = valuation("end", 14, "100", cash="50", positions=[position("1", "50")])
    split = OBSERVATION_ADAPTER.validate_python(
        {
            **common("split", 11),
            "kind": "corporate_action",
            "action": "split",
            "ticker": "NVDA",
            "split_ratio": "2",
        }
    )
    sold = FillObservation(
        **common("sold", 12),
        ticker="NVDA",
        side="SELL",
        quantity=Decimal(2),
        price=Decimal(50),
        gross_notional=Decimal(100),
        origin="external",
    )
    reopened = FillObservation(
        **common("reopened", 13),
        ticker="NVDA",
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(50),
        gross_notional=Decimal(50),
        origin="external",
    )
    overview, _ = materialize(conn, [start, end, split, sold, reopened, coverage(14)])
    episodes = overview["holding_episodes"]
    assert episodes["status"] == "available"
    assert [item["status"] for item in episodes["items"]] == ["closed", "open"]
    assert episodes["items"][0]["episode_id"] != episodes["items"][1]["episode_id"]
    assert overview["return_percent"] == "0.000000"
    conn.close()


def test_partial_fill_canceled_remainder_keeps_actual_quantity_and_unknown_cost(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "source.db")
    start = valuation("start", 10, "100")
    end = valuation("end", 12, "100", cash="80", positions=[position("2", "10")])
    fill = FillObservation(
        **common("partial", 11),
        ticker="NVDA",
        side="BUY",
        quantity=Decimal(2),
        price=Decimal(10),
        gross_notional=Decimal(20),
        origin="external",
        order_state="canceled",
        canceled_quantity=Decimal(8),
    )
    overview, _ = materialize(conn, [start, fill, end, coverage()])
    assert overview["positions"][0]["shares"] == "2"
    assert overview["positions"][0]["average_cost"] is None
    assert overview["recent_fills"][0]["gross_notional"] == "20"
    assert overview["recent_fills"][0]["canceled_quantity"] == "8"
    assert overview["holding_episodes"]["items"][0]["quantity"] == "2"
    conn.close()


def test_missing_quote_preserves_position_and_unfunded_all_cash_sold_out_states(
    tmp_path: Path,
) -> None:
    conn = connect(tmp_path / "source.db")
    partial = valuation(
        "partial", 10, "100", cash="0", positions=[{"ticker": "NVDA"}], complete=False
    )
    overview, ranges = materialize(conn, [partial])
    assert overview["positions"][0]["ticker"] == "NVDA"
    assert overview["positions"][0]["market_value"] is None
    assert overview["portfolio_state"] == "partial"
    assert ranges["All"]["status"] == "unavailable"
    assert materialize(conn, [valuation("zero", 10, "0")])[0]["portfolio_state"] == "unfunded"
    assert materialize(conn, [valuation("cash", 10, "100")])[0]["portfolio_state"] == "all_cash"
    start = valuation("start", 10, "100", cash="0", positions=[position("1", "100")])
    sold = FillObservation(
        **common("sold", 11),
        ticker="NVDA",
        side="SELL",
        quantity=Decimal(1),
        price=Decimal(100),
        gross_notional=Decimal(100),
        origin="external",
    )
    assert (
        materialize(conn, [start, sold, valuation("end", 12, "100"), coverage()])[0][
            "portfolio_state"
        ]
        == "sold_out"
    )
    conn.close()


def test_public_performance_uses_reporting_and_exact_benchmark_dates(tmp_path: Path) -> None:
    source, public = tmp_path / "source.db", tmp_path / "public.db"
    conn = connect(source)
    start, end = valuation("start", 10, "100"), valuation("end", 12, "110")
    for observation in (start, end, coverage()):
        ingest(conn, observation)
    for day, price in ((10, 100), (12, 105)):
        conn.execute(
            "INSERT INTO daily_prices VALUES('QQQ', ?, ?, ?, ?, ?, ?, 1000, 'test', ?)",
            (f"2026-06-{day}", price, price, price, price, price, end.occurred_at.isoformat()),
        )
    conn.commit()
    conn.close()
    publish(source, public, live_account_id=ACCOUNT)
    client = TestClient(create_public_app(public))
    response = client.get("/api/public/v2/portfolios/live/performance?range=All")
    assert response.status_code == 200
    assert response.json()["return_percent"] == "10.000000"
    assert response.json()["benchmarks"][0]["return_percent"] == "5.000000"
    assert response.json()["benchmarks"][1]["reason"] == "matching_adjusted_prices_missing"
    assert ACCOUNT not in response.text
    assert (
        client.get("/api/public/v2/portfolios/paper/performance").json()["status"] == "unavailable"
    )
    assert client.get("/api/public/v2/portfolios/live/performance?range=1D").status_code == 422


def test_conflicting_valuation_instant_requires_correction(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    ingest(conn, valuation("first", 10, "100"))
    with pytest.raises(ValueError, match="valuation instant"):
        ingest(conn, valuation("second", 10, "110"))
    conn.close()


def test_external_security_transfer_links_flow_and_updates_episode(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    before, after, cash_flow = flow_facts("100", "100", "200")
    transfer = FlowObservation.model_validate(
        {**cash_flow.model_dump(), "flow_type": "transfer_in"}
    )
    action = OBSERVATION_ADAPTER.validate_python(
        {
            **common("security_transfer", 11, 15),
            "kind": "corporate_action",
            "action": "transfer_in",
            "ticker": "NVDA",
            "quantity": "1",
            "flow_external_id": "flow",
        }
    )
    for observation in (before, after, transfer, action):
        ingest(conn, observation)
    start = valuation("start", 10, "100")
    end = valuation("end", 12, "200", cash="100", positions=[position("1", "100")])
    overview, ranges = materialize(conn, [start, before, after, transfer, action, end, coverage()])
    assert ranges["All"]["return_percent"] == "0.000000"
    assert overview["holding_episodes"]["items"][0]["quantity"] == "1"
    conn.close()


def test_chart_sampling_preserves_quality_gaps_and_full_series_drawdown(tmp_path: Path) -> None:
    from datetime import timedelta

    conn = connect(tmp_path / "source.db")
    beginning = datetime(2023, 1, 1, 20, tzinfo=UTC)
    values = []
    for index in range(1000):
        instant = beginning + timedelta(days=index)
        value = valuation(
            str(index),
            10,
            "70" if index == 103 else "100",
            occurred_at=instant,
            recorded_at=instant,
            session_date=instant.date(),
            complete=index != 101,
        )
        values.append(value)
    complete_coverage = CoverageObservation(
        **common("coverage", 12),
        start_at=beginning,
        end_at=values[-1].occurred_at,
        external_flows_complete=True,
    )
    _, ranges = materialize(conn, [*values, complete_coverage])
    history = ranges["All"]["history"]
    assert len(history) <= 400
    assert any(
        point["at"] == values[101].occurred_at.isoformat() and point["quality"] == "partial"
        for point in history
    )
    assert history[0]["at"] == values[0].occurred_at.isoformat()
    assert history[-1]["at"] == values[-1].occurred_at.isoformat()
    assert ranges["All"]["observed_drawdown_percent"] == "-30.000000"
    assert ranges["1M"]["period_label"].startswith("Since ")
    conn.close()


def test_trusted_json_cli_ingests_idempotently(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    path = tmp_path / "observations.json"
    path.write_text(json.dumps([valuation("close", 10, "100").model_dump(mode="json")]))
    command = [
        sys.executable,
        "-m",
        "app.performance.storage",
        "--db",
        str(tmp_path / "source.db"),
        "--input",
        str(path),
        "--mode",
        "live",
        "--account-id",
        ACCOUNT,
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(first.stdout) == {"inserted": 1, "unchanged": 0}
    assert json.loads(second.stdout) == {"inserted": 0, "unchanged": 1}


def test_unknown_fee_stays_unknown_and_voided_correction_preserves_history(tmp_path: Path) -> None:
    conn = connect(tmp_path / "source.db")
    fill = FillObservation(
        **common("fill", 11),
        ticker="NVDA",
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        gross_notional=Decimal(10),
        origin="external",
    )
    assert fill.fee is None
    ingest(conn, fill)
    correction = FillObservation.model_validate(
        {**fill.model_dump(), "observation_id": "void", "supersedes": "fill", "voided": True}
    )
    ingest(conn, correction)
    assert current_observations(conn, mode="live", account_id=ACCOUNT) == []
    assert conn.execute("SELECT COUNT(*) FROM reporting_observations").fetchone()[0] == 2
    conn.close()


def test_agent_fill_cannot_change_linked_decision_ticker_or_side(tmp_path: Path) -> None:
    from app.schemas.decision_record import InvestmentDecisionRecord
    from app.state.pipeline import process_decision
    from tests.fixtures.decision_records import valid_decision_record_data

    conn = connect(tmp_path / "source.db")
    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data())
    process_decision(conn, record.model_dump(), received_at=record.created_at)
    fill = FillObservation.model_validate(
        {
            **common("fill", 11),
            "mode": "paper",
            "account_id": "paper",
            "ticker": "AMD",
            "side": "BUY",
            "quantity": "1",
            "price": "10",
            "gross_notional": "10",
            "origin": "agent",
            "decision_id": record.decision_id,
        }
    )
    with pytest.raises(ValueError, match="matching execution mode"):
        ingest(conn, fill)
    with pytest.raises(ValueError, match="matching execution mode"):
        ingest(
            conn,
            FillObservation.model_validate({**fill.model_dump(), "ticker": "NVDA", "side": "SELL"}),
        )
    assert ingest(conn, FillObservation.model_validate({**fill.model_dump(), "ticker": "NVDA"}))
    conn.close()


def test_chart_with_exactly_four_hundred_mandatory_markers_stays_bounded(tmp_path: Path) -> None:
    from datetime import timedelta

    conn = connect(tmp_path / "source.db")
    beginning = datetime(2023, 1, 1, 20, tzinfo=UTC)
    values = []
    for index in range(800):
        instant = beginning + timedelta(days=index)
        values.append(
            valuation(
                str(index),
                10,
                "100",
                occurred_at=instant,
                recorded_at=instant,
                session_date=instant.date(),
                complete=index % 2 == 0 if index <= 398 else True,
            )
        )
    complete_coverage = CoverageObservation(
        **common("coverage", 12),
        start_at=beginning,
        end_at=values[-1].occurred_at,
        external_flows_complete=True,
    )
    _, ranges = materialize(conn, [*values, complete_coverage])
    assert len(ranges["All"]["history"]) == 400
    assert ranges["All"]["history"][-1]["at"] == values[-1].occurred_at.isoformat()
    conn.close()


def test_daily_pnl_withholds_coincident_flow_endpoint() -> None:
    start = valuation("start", 10, "100")
    _, _, flow = flow_facts()
    end = valuation(
        "end",
        11,
        "210",
        occurred_at=flow.occurred_at,
        phase="intraday",
        previous_session_date="2026-06-10",
    )
    result = daily_pnl(end, [start, end], [flow], [coverage()])
    assert result["reason"] == "coincident_flow_endpoint_order_unknown"
    assert result["amount"] is None


def test_daily_pnl_derives_calendar_baseline_without_redundant_previous_date() -> None:
    start, end = valuation("start", 10, "100"), valuation("end", 11, "131")
    result = daily_pnl(end, [start, end], [], [coverage()])
    assert result["status"] == "available" and result["amount"] == "31"
    assert result["baseline_at"] == start.occurred_at.isoformat()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"session_date": "2026-06-10"}, "session_timestamp_mismatch"),
        (
            {"occurred_at": datetime(2026, 6, 11, 19, tzinfo=UTC)},
            "valuation_precedes_session_close",
        ),
        ({"previous_session_date": "2026-06-09"}, "previous_session_date_mismatch"),
    ],
)
def test_daily_and_benchmark_withhold_inconsistent_session_facts(
    changes: dict[str, Any], reason: str
) -> None:
    start, end = valuation("start", 10, "100"), valuation("end", 11, "131", **changes)
    assert daily_pnl(end, [start, end], [], [coverage()])["reason"] == reason
    conn = connect(":memory:")
    _, ranges = materialize(conn, [start, end, coverage()])
    if reason != "previous_session_date_mismatch":
        assert all(item["status"] == "unavailable" for item in ranges["All"]["benchmarks"])
    conn.close()


def test_large_bounded_price_product_fails_validation_cleanly() -> None:
    with pytest.raises(ValidationError, match="position value"):
        ReportingPosition(
            ticker="NVDA",
            quantity=Decimal("9999999999999999999999"),
            price=Decimal("9999999999999999999999"),
            market_value=Decimal("1"),
        )


def test_two_flows_cannot_reuse_one_boundary_pair() -> None:
    before, after, flow = flow_facts()
    second = flow.model_copy(
        update={"observation_id": "second", "external_event_id": "second", "sequence": 1}
    )
    result = linked_return(
        valuation("start", 10, "100"),
        valuation("end", 12, "310"),
        {"before": before, "after": after},
        [flow, second],
        [coverage()],
    )
    assert result["reason"] == "external_flow_boundary_reused"


def test_formerly_funded_zero_balance_is_not_unfunded() -> None:
    conn = connect(":memory:")
    overview, _ = materialize(conn, [valuation("start", 10, "100"), valuation("end", 12, "0")])
    assert overview["portfolio_state"] == "zero_balance"
    conn.close()
