import pytest

from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.schemas.order_intent import OrderIntentStatus, OrderSide, OrderType
from tests.fixtures.decision_records import decision_record_with, valid_decision_record

approved = PolicyResult(approved=True)


def test_approved_buy_creates_buy_intent():
    record = valid_decision_record()

    intent = create_order_intent(record, approved)

    assert intent.side == OrderSide.BUY
    assert intent.ticker == "NVDA"
    assert intent.target_weight == record.final_target_weight
    assert intent.order_type == OrderType.LIMIT
    assert intent.status == OrderIntentStatus.CREATED


def test_intent_id_is_deterministic():
    record = valid_decision_record()

    first = create_order_intent(record, approved)
    second = create_order_intent(record, approved)

    assert first.order_intent_id == second.order_intent_id == "oi_dec_001"


def test_trim_creates_sell_intent():
    record = decision_record_with(decision="TRIM")

    intent = create_order_intent(record, approved)

    assert intent.side == OrderSide.SELL


def test_sell_creates_sell_intent():
    record = decision_record_with(decision="SELL")

    intent = create_order_intent(record, approved)

    assert intent.side == OrderSide.SELL


def test_rejected_decision_raises():
    record = valid_decision_record()
    rejected = PolicyResult(approved=False, reasons=["x"])

    with pytest.raises(ValueError):
        create_order_intent(record, rejected)


def test_hold_raises():
    record = decision_record_with(decision="HOLD")

    with pytest.raises(ValueError):
        create_order_intent(record, approved)


def test_created_at_is_timezone_aware():
    record = valid_decision_record()

    intent = create_order_intent(record, approved)

    assert intent.created_at.tzinfo is not None
