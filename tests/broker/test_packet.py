from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.broker.config import get_live_profile, load_live_profiles
from app.broker.packet import build_execution_packet
from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.live_execution import (
    BrokerPreflight,
    ExecutionProfile,
    LiveExecutionPacket,
    LiveProfilesConfig,
)
from app.schemas.order_intent import ExecutionMode, OrderIntent
from tests.fixtures.decision_records import valid_decision_record

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)


def _profile(**updates: object) -> ExecutionProfile:
    data: dict[str, object] = {
        "execution_profile_id": "codex",
        "agent_provider": "CODEX",
        "account_alias": "codex-agentic",
        "broker_account_fingerprint": "0123456789abcdef",
        "enabled": True,
        "account_equity_cap": 100.0,
        "max_order_notional": 20.0,
        "max_quote_age_seconds": 15,
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
    assert get_live_profile(config, "codex").account_equity_cap == 100.0


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
    assert packet.limit_price == 200.1
    assert packet.require_human_approval is False


@pytest.mark.parametrize(
    ("profile_updates", "preflight_updates", "reason"),
    [
        ({"enabled": False}, {}, "live_profile_disabled"),
        ({}, {"execution_profile_id": "claude"}, "preflight_profile_mismatch"),
        ({}, {"account_equity": 101.0}, "account_equity_cap_exceeded"),
        ({}, {"quote_at": NOW - timedelta(seconds=16)}, "stale_quote"),
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
