from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioInputs(PolicyModel):
    holdings_count: int = Field(ge=0)
    buy_add_trades_today: int = Field(ge=0)
    sell_trim_trades_today: int = Field(ge=0)
    primary_theme_weights: dict[str, float] = Field(default_factory=dict)


class PolicyInputIdentity(PolicyModel):
    portfolio_snapshot_id: str | None = None
    regime_snapshot_id: str | None = None
    regime_snapshot_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    current_weight: float | None = Field(default=None, ge=0, le=1)


class RecordedRegime(PolicyModel):
    snapshot_date: date
    state: Literal["GREEN", "YELLOW", "RED"]
    raw_state: Literal["GREEN", "YELLOW", "RED"]
    score: int
    computed_at: AwareDatetime
    components: dict[str, JsonValue]


class RuleDefinition(PolicyModel):
    rule_id: str
    name: str
    failure_explanation: str
    threshold: float | int | bool | str | None
    comparator: Literal["eq", "lt", "lte", "gte"]
    unit: Literal["fraction", "count", "boolean", "regime"]
    scope: Literal["decision", "proposal", "portfolio"] = "decision"


class RuleCheck(PolicyModel):
    name: str | None = None
    failure_explanation: str | None = None
    rule_id: str
    version: str
    category: Literal["decision_policy", "posture", "execution_control"] = "decision_policy"
    scope: Literal["decision", "proposal", "portfolio"]
    result: Literal["passed", "failed", "not_applicable", "missing_input"]
    observed: float | int | bool | str | None
    threshold: float | int | bool | str | None
    comparator: Literal["eq", "lt", "lte", "gte"]
    unit: Literal["fraction", "count", "boolean", "regime"]
    headroom: float | None = None


class PolicyEvaluationRecord(PolicyModel):
    decision_id: str
    execution_mode: Literal["PAPER", "LIVE"]
    execution_profile_id: str
    evaluated_at: AwareDatetime
    policy_version: str
    validator_version: str
    validator_schema_sha256: str
    authored_schema_version: str | None = None
    approved: bool
    reasons: list[str]
    checks: list[RuleCheck]
    portfolio: PortfolioInputs | None
    true_regime_state: str | None
    input_identity: PolicyInputIdentity
    regime_snapshot: RecordedRegime | None = None
    portfolio_snapshot: dict[str, JsonValue] | None = None
