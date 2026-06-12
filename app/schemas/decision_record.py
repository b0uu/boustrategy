from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AssetType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"


class Decision(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    TRIM = "TRIM"
    SELL = "SELL"
    HOLD = "HOLD"
    PASS = "PASS"
    WATCHLIST = "WATCHLIST"


class OperatingMode(StrEnum):
    CAPITAL_DEPLOYMENT = "CAPITAL_DEPLOYMENT"
    PORTFOLIO_MANAGEMENT = "PORTFOLIO_MANAGEMENT"
    DE_RISKING = "DE_RISKING"


class RegimeState(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class XSignalUsageType(StrEnum):
    IDEA_SOURCE = "IDEA_SOURCE"
    CONFIRMATION = "CONFIRMATION"
    COUNTER_THESIS = "COUNTER_THESIS"
    CROWDING_WARNING = "CROWDING_WARNING"
    IRRELEVANT = "IRRELEVANT"


class SourceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_timestamp: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    public_safe: bool


class XSignalUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used: bool = False
    usage_type: XSignalUsageType = XSignalUsageType.IRRELEVANT
    summary: str = ""
    confirmed_outside_x: bool = False

    @model_validator(mode="after")
    def require_summary_when_used(self) -> "XSignalUsage":
        if self.used and not self.summary.strip():
            raise ValueError("x_signal_usage.summary is required when X is used")
        return self


class InvestmentDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    created_at: datetime

    ticker: str = Field(min_length=1, max_length=12)
    asset_type: AssetType
    decision: Decision

    theme_ids: list[str] = Field(default_factory=list)
    strategy_belief_ids: list[str] = Field(default_factory=list)

    trigger_id: str | None = None
    operating_mode: OperatingMode
    regime_state: RegimeState
    source_pack_id: str = Field(min_length=1)

    initial_thesis: str = ""
    counter_thesis: str = ""
    adversarial_refinement: str = ""
    refined_thesis: str = ""
    what_is_priced_in: str = ""

    thesis_invalidation_criteria: list[str] = Field(default_factory=list)
    add_conditions: list[str] = Field(default_factory=list)
    trim_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)

    proposed_target_weight: float = Field(ge=0.0, le=1.0)
    final_target_weight: float = Field(ge=0.0, le=1.0)

    source_claims: list[SourceClaim] = Field(default_factory=list)
    x_signal_usage: XSignalUsage = Field(default_factory=XSignalUsage)

    public_summary: str = ""
    internal_notes: str = ""

    order_intent_id: str | None = None
    broker_execution_record_id: str | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_local_consistency(self) -> "InvestmentDecisionRecord":
        if self.final_target_weight > self.proposed_target_weight:
            raise ValueError("final_target_weight cannot exceed proposed_target_weight")

        actionable_decisions = {
            Decision.BUY,
            Decision.ADD,
            Decision.TRIM,
            Decision.SELL,
        }
        if self.decision in actionable_decisions and not self.refined_thesis.strip():
            raise ValueError("refined_thesis is required for actionable decisions")

        return self
