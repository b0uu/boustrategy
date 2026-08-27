from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.broker_execution import BrokerExecutionRecord


def broker_execution_data() -> dict[str, object]:
    return {
        "broker_execution_record_id": "be_001",
        "order_intent_id": "oi_dec_001",
        "execution_packet_id": "ep_codex_oi_dec_001",
        "execution_profile_id": "codex",
        "account_alias": "codex-agentic",
        "ticker": "NVDA",
        "side": "BUY",
        "order_type": "LIMIT",
        "requested_notional": 15.0,
        "limit_price": 200.0,
        "submitted_at": datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
        "status": "SUBMITTED",
        "broker_order_id": "rh_001",
        "execution_price": 0.0,
    }


def test_submitted_execution_record_is_valid() -> None:
    record = BrokerExecutionRecord.model_validate(broker_execution_data())

    assert record.status == "SUBMITTED"
    assert record.requested_notional == 15.0


def test_filled_execution_requires_positive_execution_price() -> None:
    data = broker_execution_data()
    data["status"] = "FILLED"

    with pytest.raises(ValidationError, match="execution_price"):
        BrokerExecutionRecord.model_validate(data)
