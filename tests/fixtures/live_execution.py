from datetime import UTC, datetime

from app.schemas.live_execution import LiveExecutionPacket
from app.schemas.order_intent import OrderIntent


def live_execution_packet(intent: OrderIntent) -> LiveExecutionPacket:
    return LiveExecutionPacket(
        execution_packet_id=f"ep_{intent.execution_profile_id}_{intent.order_intent_id}",
        order_intent_id=intent.order_intent_id,
        decision_id=intent.decision_id,
        execution_profile_id=intent.execution_profile_id,
        agent_provider="CODEX",
        account_alias="codex-agentic",
        created_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        expires_at=datetime(2026, 8, 26, 14, 2, tzinfo=UTC),
        ticker=intent.ticker,
        side=intent.side,
        order_type=intent.order_type,
        target_weight=intent.target_weight,
        account_equity=100.0,
        current_position_value=0.0,
        notional=12.0,
        limit_price=200.0,
        quote_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        spread_bps=10.0,
        require_human_approval=False,
    )
