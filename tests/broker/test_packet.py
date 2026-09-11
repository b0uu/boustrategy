from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.broker.config import get_live_profile, load_live_profiles
from app.broker.packet import allowed_price, build_execution_packet
from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.live_execution import (
    BrokerPreflight,
    ExecutionProfile,
    LiveExecutionPacket,
    LiveProfilesConfig,
)
from app.schemas.order_intent import ExecutionMode, OrderIntent
from tests.fixtures.decision_records import valid_decision_record, valid_decision_record_data

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)


def _profile(**updates: object) -> ExecutionProfile:
    data: dict[str, object] = {
        "execution_profile_id": "codex",
        "agent_provider": "CODEX",
        "account_alias": "codex-agentic",
        "broker_account_fingerprint": "0123456789abcdef",
        "enabled": True,
        "max_order_notional": 20.0,
        "max_quote_age_seconds": 60,
        "max_spread_bps": 50.0,
        "require_human_approval": False,
    }
    data.update(updates)
    return ExecutionProfile.model_validate(data)


def _preflight(**updates: object) -> BrokerPreflight:
    data: dict[str, object] = {
        "execution_profile_id": "codex",
        "broker_account_fingerprint": "0123456789abcdef",
        "account_equity": 100.0,
        "buying_power": 100.0,
        "current_position_value": 0.0,
        "ticker": "NVDA",
        "bid": 199.9,
        "ask": 200.1,
        "quote_at": NOW - timedelta(seconds=2),
        "tradable": True,
        "fractionable": True,
        "regular_market_hours": True,
    }
    data.update(updates)
    return BrokerPreflight.model_validate(data)


def _live_intent() -> OrderIntent:
    return create_order_intent(
        valid_decision_record(),
        PolicyResult(approved=True),
        created_at=NOW,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )


def test_example_config_has_two_disabled_isolated_profiles() -> None:
    root = Path(__file__).parents[2]

    config = load_live_profiles(root / "ops" / "live.example.json")

    assert {profile.execution_profile_id for profile in config.profiles} == {"codex", "claude"}
    assert all(not profile.enabled for profile in config.profiles)
    assert get_live_profile(config, "codex").max_order_notional == 20.0


def test_profiles_require_unique_account_aliases() -> None:
    codex = _profile()
    claude = _profile(execution_profile_id="claude", agent_provider="CLAUDE")

    with pytest.raises(ValidationError, match="account_alias"):
        LiveProfilesConfig(profiles=[codex, claude])


def test_build_packet_enforces_profile_and_automatic_safety_limits() -> None:
    packet = build_execution_packet(
        _live_intent(),
        valid_decision_record(),
        _profile(),
        _preflight(),
        created_at=NOW,
    )

    assert packet.execution_packet_id == "ep_codex_oi_dec_001_20260827T140000000000Z"
    assert packet.account_alias == "codex-agentic"
    assert packet.notional == 12.0
    assert packet.limit_price == 202.1
    assert packet.require_human_approval is False


def test_build_packet_allows_equity_growth_within_order_brake() -> None:
    packet = build_execution_packet(
        _live_intent(),
        valid_decision_record(),
        _profile(),
        _preflight(account_equity=150.0, buying_power=150.0),
        created_at=NOW,
    )

    assert packet.account_equity == 150.0
    assert packet.notional == 18.0


@pytest.mark.parametrize(
    ("profile_updates", "preflight_updates", "reason"),
    [
        ({"enabled": False}, {}, "live_profile_disabled"),
        ({}, {"execution_profile_id": "claude"}, "preflight_profile_mismatch"),
        ({}, {"quote_at": NOW - timedelta(seconds=61)}, "stale_quote"),
        ({}, {"regular_market_hours": False}, "outside_regular_market_hours"),
        ({}, {"fractionable": False}, "ticker_not_fractionable"),
    ],
)
def test_packet_fails_closed(
    profile_updates: dict[str, object],
    preflight_updates: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        build_execution_packet(
            _live_intent(),
            valid_decision_record(),
            _profile(**profile_updates),
            _preflight(**preflight_updates),
            created_at=NOW,
        )


def test_execution_packet_rejects_inconsistent_times() -> None:
    packet = build_execution_packet(
        _live_intent(),
        valid_decision_record(),
        _profile(),
        _preflight(),
        created_at=NOW,
    )
    invalid = {**packet.model_dump(), "expires_at": packet.created_at}

    with pytest.raises(ValidationError, match="expires_at must be after created_at"):
        LiveExecutionPacket.model_validate(invalid)


@pytest.mark.parametrize("updates", [{"target_weight": 0.19}, {"side": "SELL"}])
def test_packet_rejects_changed_approved_intent(updates: dict[str, object]) -> None:
    intent = OrderIntent.model_validate({**_live_intent().model_dump(), **updates})
    with pytest.raises(ValueError, match="decision_intent_mismatch"):
        build_execution_packet(
            intent,
            valid_decision_record(),
            _profile(),
            _preflight(current_position_value=30),
            created_at=NOW,
        )


@pytest.mark.parametrize("ticker", ["", "AAPL"])
def test_packet_requires_quote_instrument(ticker: str) -> None:
    with pytest.raises(ValueError, match="preflight_ticker_mismatch"):
        build_execution_packet(
            _live_intent(),
            valid_decision_record(),
            _profile(),
            _preflight(ticker=ticker),
            created_at=NOW,
        )


@pytest.mark.parametrize("field", ["account_equity", "buying_power", "bid", "ask"])
@pytest.mark.parametrize("value", [float("inf"), float("nan"), -float("inf")])
def test_preflight_rejects_nonfinite_financial_inputs(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        _preflight(**{field: value})


def test_packet_refuses_a_buy_priced_above_its_entry_band() -> None:
    record = valid_decision_record().model_copy(update={"entry_price_max": 199.0})
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    with pytest.raises(ValueError, match="price_above_entry_band"):
        build_execution_packet(intent, record, _profile(), _preflight(), created_at=NOW)

    inside = record.model_copy(update={"entry_price_max": 201.0})
    packet = build_execution_packet(intent, inside, _profile(), _preflight(), created_at=NOW)
    # The ask plus the 1% guard (202.1) is capped at the decision's entry bound.
    assert packet.limit_price == 201.0

    # The allowance never carries the limit past the decision's own entry bound.
    tight = record.model_copy(update={"entry_price_max": 200.3})
    capped = build_execution_packet(intent, tight, _profile(), _preflight(), created_at=NOW)
    assert capped.limit_price == 200.3


def test_packet_requires_an_entry_band_on_every_live_buy() -> None:
    record = valid_decision_record().model_copy(update={"entry_price_max": None})
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    with pytest.raises(ValueError, match="missing_entry_price_band"):
        build_execution_packet(intent, record, _profile(), _preflight(), created_at=NOW)


def test_entry_band_bounds_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="entry_price_min cannot exceed"):
        InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "entry_price_min": 220.0, "entry_price_max": 200.0}
        )


def test_packet_refuses_a_sell_priced_below_its_exit_band() -> None:
    record = valid_decision_record().model_copy(
        update={"decision": "SELL", "final_target_weight": 0.0, "entry_price_min": 210.0}
    )
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        created_at=NOW,
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )
    preflight = _preflight(current_position_value=15.0)

    with pytest.raises(ValueError, match="price_below_exit_band"):
        build_execution_packet(intent, record, _profile(), preflight, created_at=NOW)

    inside = record.model_copy(update={"entry_price_min": 199.0})
    packet = build_execution_packet(intent, inside, _profile(), preflight, created_at=NOW)
    # The bid less the 1% guard (197.9) is held at the decision's exit bound.
    assert packet.limit_price == 199.0
    floor = record.model_copy(update={"entry_price_min": 199.7})
    held = build_execution_packet(intent, floor, _profile(), preflight, created_at=NOW)
    assert held.limit_price == 199.7


def test_the_review_price_anchors_the_allowed_range() -> None:
    reviewed = datetime(2026, 8, 27, 13, 50, tzinfo=UTC)
    record = valid_decision_record().model_copy(
        update={"entry_price_max": 230.0, "reference_price": 198.0, "reference_price_at": reviewed}
    )
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    # 1% over the reviewed 198.00 allows up to 199.98; the live ask of 200.10 is outside it.
    with pytest.raises(ValueError, match="^price_above_allowed_range$"):
        build_execution_packet(intent, record, _profile(), _preflight(), created_at=NOW)

    within = _preflight(bid=199.5, ask=199.6)
    packet = build_execution_packet(intent, record, _profile(), within, created_at=NOW)
    assert packet.limit_price == 199.98
    assert allowed_price(intent, record, within) == 199.98


def test_the_entry_ceiling_still_wins_over_the_allowed_range() -> None:
    reviewed = datetime(2026, 8, 27, 13, 50, tzinfo=UTC)
    record = valid_decision_record().model_copy(
        update={"entry_price_max": 199.0, "reference_price": 198.0, "reference_price_at": reviewed}
    )
    intent = create_order_intent(
        record,
        PolicyResult(approved=True),
        execution_mode=ExecutionMode.LIVE,
        execution_profile_id="codex",
    )

    with pytest.raises(ValueError, match="^price_above_entry_band$"):
        build_execution_packet(intent, record, _profile(), _preflight(), created_at=NOW)
    inside = _preflight(bid=198.5, ask=198.7)
    assert (
        build_execution_packet(intent, record, _profile(), inside, created_at=NOW).limit_price
        == 199.0
    )


def test_reference_price_and_time_are_recorded_together() -> None:
    with pytest.raises(ValidationError, match="recorded together"):
        InvestmentDecisionRecord.model_validate(
            {**valid_decision_record_data(), "reference_price": 198.0}
        )
