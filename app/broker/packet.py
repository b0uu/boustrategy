from datetime import UTC, datetime, timedelta

from app.schemas.decision_record import AssetType, InvestmentDecisionRecord
from app.schemas.live_execution import BrokerPreflight, ExecutionProfile, LiveExecutionPacket
from app.schemas.order_intent import ExecutionMode, OrderIntent, OrderSide, OrderType


def build_execution_packet(
    intent: OrderIntent,
    decision: InvestmentDecisionRecord,
    profile: ExecutionProfile,
    preflight: BrokerPreflight,
    *,
    created_at: datetime | None = None,
) -> LiveExecutionPacket:
    now = created_at or datetime.now(UTC)
    reasons: list[str] = []
    if not profile.enabled:
        reasons.append("live_profile_disabled")
    if intent.execution_mode != ExecutionMode.LIVE:
        reasons.append("intent_is_not_live")
    if (
        not intent.execution_profile_id
        or intent.execution_profile_id != profile.execution_profile_id
    ):
        reasons.append("intent_profile_mismatch")
    if preflight.execution_profile_id != profile.execution_profile_id:
        reasons.append("preflight_profile_mismatch")
    if preflight.broker_account_fingerprint != profile.broker_account_fingerprint:
        reasons.append("broker_account_mismatch")
    if intent.decision_id != decision.decision_id or intent.ticker != decision.ticker:
        reasons.append("decision_intent_mismatch")
    if decision.asset_type != AssetType.EQUITY:
        reasons.append("live_asset_type_not_allowed")
    if intent.order_type != OrderType.LIMIT:
        reasons.append("live_order_type_not_allowed")
    if preflight.account_equity > profile.account_equity_cap:
        reasons.append("account_equity_cap_exceeded")
    if not preflight.tradable:
        reasons.append("ticker_not_tradable")
    if not preflight.fractionable:
        reasons.append("ticker_not_fractionable")
    if not preflight.regular_market_hours:
        reasons.append("outside_regular_market_hours")
    if preflight.quote_at > now:
        reasons.append("quote_timestamp_in_future")
    quote_age = (now - preflight.quote_at).total_seconds()
    if quote_age >= profile.max_quote_age_seconds:
        reasons.append("stale_quote")

    midpoint = (preflight.bid + preflight.ask) / 2
    spread_bps = (preflight.ask - preflight.bid) / midpoint * 10_000
    if spread_bps > profile.max_spread_bps:
        reasons.append("spread_too_wide")

    target_value = intent.target_weight * preflight.account_equity
    delta_value = target_value - preflight.current_position_value
    if intent.side == OrderSide.BUY and delta_value <= 0:
        reasons.append("buy_has_non_positive_delta")
    if intent.side == OrderSide.SELL and delta_value >= 0:
        reasons.append("sell_has_non_negative_delta")
    notional = abs(delta_value)
    if notional > profile.max_order_notional:
        reasons.append("max_order_notional_exceeded")
    if intent.side == OrderSide.BUY and notional > preflight.buying_power:
        reasons.append("insufficient_buying_power")

    if reasons:
        raise ValueError(",".join(reasons))

    return LiveExecutionPacket(
        execution_packet_id=(
            f"ep_{profile.execution_profile_id}_{intent.order_intent_id}_"
            f"{now.strftime('%Y%m%dT%H%M%S%fZ')}"
        ),
        order_intent_id=intent.order_intent_id,
        decision_id=intent.decision_id,
        execution_profile_id=profile.execution_profile_id,
        agent_provider=profile.agent_provider,
        account_alias=profile.account_alias,
        created_at=now,
        expires_at=preflight.quote_at + timedelta(seconds=profile.max_quote_age_seconds),
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        target_weight=intent.target_weight,
        account_equity=preflight.account_equity,
        current_position_value=preflight.current_position_value,
        notional=round(notional, 2),
        limit_price=preflight.ask if intent.side == OrderSide.BUY else preflight.bid,
        quote_at=preflight.quote_at,
        spread_bps=spread_bps,
        require_human_approval=profile.require_human_approval,
    )
