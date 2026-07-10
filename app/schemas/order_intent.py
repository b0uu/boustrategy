from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderIntentStatus(StrEnum):
    CREATED = "CREATED"


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_intent_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    created_at: AwareDatetime
    ticker: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    target_weight: float = Field(ge=0.0, le=1.0)
    status: OrderIntentStatus = OrderIntentStatus.CREATED
