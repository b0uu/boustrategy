from datetime import UTC, datetime

from pydantic import AwareDatetime

from app.policy.decision_policy import PolicyResult
from app.schemas.decision_record import Decision, InvestmentDecisionRecord
from app.schemas.order_intent import OrderIntent, OrderSide

_INTENT_SIDES = {
    Decision.BUY: OrderSide.BUY,
    Decision.ADD: OrderSide.BUY,
    Decision.TRIM: OrderSide.SELL,
    Decision.SELL: OrderSide.SELL,
}


def create_order_intent(
    record: InvestmentDecisionRecord,
    policy_result: PolicyResult,
    created_at: AwareDatetime | None = None,
) -> OrderIntent:
    if not policy_result.approved:
        raise ValueError("cannot create an order intent from a rejected decision")

    side = _INTENT_SIDES.get(record.decision)
    if side is None:
        raise ValueError(
            f"decision {record.decision} is not actionable and cannot produce an order intent"
        )

    return OrderIntent(
        order_intent_id=f"oi_{record.decision_id}",
        decision_id=record.decision_id,
        created_at=created_at or datetime.now(UTC),
        ticker=record.ticker,
        side=side,
        target_weight=record.final_target_weight,
    )
