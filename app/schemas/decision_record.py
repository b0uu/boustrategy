import re
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.public_authoring import PublicNarrative

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")


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


class SourceType(StrEnum):
    SEC = "SEC"
    COMPANY_IR = "COMPANY_IR"
    NEWS = "NEWS"
    X = "X"
    PRICE_DATA = "PRICE_DATA"
    MACRO = "MACRO"
    ETF_ISSUER = "ETF_ISSUER"
    INTERNAL_MEMO = "INTERNAL_MEMO"


class SourceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    source_type: SourceType
    source_timestamp: AwareDatetime
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
        if self.used:
            if not self.summary.strip():
                raise ValueError("x_signal_usage.summary is required when X is used")
            if self.usage_type == XSignalUsageType.IRRELEVANT:
                raise ValueError("x_signal_usage.usage_type cannot be IRRELEVANT when X is used")
        else:
            if self.usage_type != XSignalUsageType.IRRELEVANT:
                raise ValueError("x_signal_usage.usage_type must be IRRELEVANT when X is not used")
            if self.confirmed_outside_x:
                raise ValueError(
                    "x_signal_usage.confirmed_outside_x must be false when X is not used"
                )
        return self


class InvestmentDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    schema_version: str | None = None
    public_narrative: PublicNarrative | None = None
    created_at: AwareDatetime

    ticker: str = Field(min_length=1, max_length=12)
    asset_type: AssetType
    decision: Decision

    theme_ids: list[str] = Field(default_factory=list)
    primary_theme_id: str | None = None
    strategy_belief_ids: list[str] = Field(default_factory=list)

    trigger_id: str | None = None
    operating_mode: OperatingMode
    regime_state: RegimeState
    extraordinary_opportunity: bool = False
    extraordinary_justification: str = ""
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

    # The price range in which this thesis still holds. Live execution refuses a
    # packet outside it, so a move between authoring and placement cannot turn a
    # researched entry into chasing an already-priced-in move.
    entry_price_max: float | None = Field(default=None, gt=0.0)
    entry_price_min: float | None = Field(default=None, gt=0.0)

    # The price the review actually read from an opened quote page, and the time that page
    # displayed. Execution measures drift from this price, so an order can't fill far from
    # the level the reasoning saw.
    reference_price: float | None = Field(default=None, gt=0.0)
    reference_price_at: AwareDatetime | None = None

    source_claims: list[SourceClaim] = Field(default_factory=list)
    x_signal_usage: XSignalUsage = Field(default_factory=XSignalUsage)

    public_summary: str = ""
    internal_notes: str = ""

    order_intent_id: str | None = None
    broker_execution_record_id: str | None = None

    @model_validator(mode="after")
    def ordered_entry_band(self) -> "InvestmentDecisionRecord":
        if (
            self.entry_price_min is not None
            and self.entry_price_max is not None
            and self.entry_price_min > self.entry_price_max
        ):
            raise ValueError("entry_price_min cannot exceed entry_price_max")
        if (self.reference_price is None) != (self.reference_price_at is None):
            raise ValueError("reference_price and reference_price_at are recorded together")
        return self

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized):
            raise ValueError(
                "ticker must be 1-12 characters of A-Z, digits, '.' or '-', starting with a letter"
            )
        return normalized

    @model_validator(mode="after")
    def public_stage_times(self) -> "InvestmentDecisionRecord":
        if self.public_narrative:
            for stage in self.public_narrative.stages:
                if any(
                    at and at > self.created_at for at in (stage.started_at, stage.completed_at)
                ):
                    raise ValueError("public stage cannot follow decision creation")
        return self

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

        if self.extraordinary_opportunity and not self.extraordinary_justification.strip():
            raise ValueError(
                "extraordinary_justification is required when extraordinary_opportunity is true"
            )

        if self.primary_theme_id is not None and self.primary_theme_id not in self.theme_ids:
            raise ValueError("primary_theme_id must be one of theme_ids")

        if self.decision in {Decision.BUY, Decision.ADD} and self.primary_theme_id is None:
            raise ValueError("primary_theme_id is required for BUY and ADD decisions")

        return self
