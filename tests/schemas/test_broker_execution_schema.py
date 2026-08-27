from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.broker_execution import BrokerExecutionRecord


def broker_execution_data() -> dict[str, object]:
    return {
        "broker_execution_record_id": "be_001",
        "order_intent_id": "oi_dec_001",
        "ticker": "NVDA",
        "side": "BUY",
        "order_type": "LIMIT",
        "notional_or_quantity": "$15.00 notional",
        "limit_price": 200.0,
        "submitted_at": datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        "status": "SUBMITTED",
        "broker_order_id": "rh_001",
        "execution_price": 0.0,
        "raw_broker_payload_private": True,
    }


def test_submitted_execution_record_is_valid() -> None:
    record = BrokerExecutionRecord.model_validate(broker_execution_data())

    assert record.status == "SUBMITTED"
    assert record.raw_broker_payload_private is True


def test_filled_execution_requires_positive_execution_price() -> None:
    data = broker_execution_data()
    data["status"] = "FILLED"

    with pytest.raises(ValidationError, match="execution_price"):
        BrokerExecutionRecord.model_validate(data)


def test_raw_broker_payload_must_remain_private() -> None:
    data = broker_execution_data()
    data["raw_broker_payload_private"] = False

    with pytest.raises(ValidationError):
        BrokerExecutionRecord.model_validate(data)
