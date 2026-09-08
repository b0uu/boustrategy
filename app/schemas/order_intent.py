from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderIntentStatus(StrEnum):
    CREATED = "CREATED"


class ExecutionMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    order_intent_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    created_at: AwareDatetime
    ticker: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    target_weight: float = Field(ge=0.0, le=1.0)
    status: OrderIntentStatus = OrderIntentStatus.CREATED
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    execution_profile_id: str = ""

    @model_validator(mode="after")
    def require_profile_only_for_live_intents(self) -> "OrderIntent":
        if self.execution_mode == ExecutionMode.LIVE and not self.execution_profile_id.strip():
            raise ValueError("execution_profile_id is required for live intents")
        if self.execution_mode == ExecutionMode.PAPER and self.execution_profile_id:
            raise ValueError("execution_profile_id must be empty for paper intents")
        return self
