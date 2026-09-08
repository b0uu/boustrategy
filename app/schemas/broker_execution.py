from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.order_intent import OrderSide, OrderType


class BrokerExecutionStatus(StrEnum):
    REVIEWED = "REVIEWED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class BrokerExecutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    broker_execution_record_id: str = Field(min_length=1)
    order_intent_id: str = Field(min_length=1)
    execution_packet_id: str = Field(min_length=1)
    execution_profile_id: str = Field(min_length=1)
    account_alias: str = Field(min_length=1)
    ticker: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType
    requested_notional: float = Field(gt=0.0)
    limit_price: float = Field(ge=0.0)
    submitted_at: AwareDatetime
    status: BrokerExecutionStatus
    broker_order_id: str = Field(min_length=1)
    execution_price: float = Field(ge=0.0)

    @model_validator(mode="after")
    def require_execution_price_for_fills(self) -> "BrokerExecutionRecord":
        if (
            self.status
            in {
                BrokerExecutionStatus.FILLED,
                BrokerExecutionStatus.PARTIALLY_FILLED,
            }
            and self.execution_price <= 0
        ):
            raise ValueError("execution_price must be positive for filled executions")
        return self


class BrokerExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    broker_event_id: str = Field(min_length=1)
    broker_execution_record_id: str = Field(min_length=1)
    order_intent_id: str = Field(min_length=1)
    execution_packet_id: str = Field(min_length=1)
    execution_profile_id: str = Field(min_length=1)
    status: BrokerExecutionStatus
    occurred_at: AwareDatetime
    detail: str = ""
