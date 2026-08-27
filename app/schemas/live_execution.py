from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.order_intent import OrderSide, OrderType


class AgentProvider(StrEnum):
    CODEX = "CODEX"
    CLAUDE = "CLAUDE"


class ExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_profile_id: str = Field(min_length=1)
    agent_provider: AgentProvider
    account_alias: str = Field(min_length=1)
    broker_account_fingerprint: str = Field(default="", pattern=r"^[a-f0-9]{0,16}$")
    enabled: bool = False
    account_equity_cap: float = Field(gt=0.0)
    max_order_notional: float = Field(gt=0.0)
    max_quote_age_seconds: int = Field(gt=0, le=60)
    max_spread_bps: float = Field(gt=0.0)
    require_human_approval: bool = False

    @model_validator(mode="after")
    def keep_order_cap_within_account_cap(self) -> "ExecutionProfile":
        if self.max_order_notional > self.account_equity_cap:
            raise ValueError("max_order_notional cannot exceed account_equity_cap")
        if self.enabled and len(self.broker_account_fingerprint) != 16:
            raise ValueError("enabled profiles require a broker_account_fingerprint")
        return self


class LiveProfilesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[ExecutionProfile] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_routing(self) -> "LiveProfilesConfig":
        profile_ids = [profile.execution_profile_id for profile in self.profiles]
        account_aliases = [profile.account_alias for profile in self.profiles]
        fingerprints = [
            profile.broker_account_fingerprint
            for profile in self.profiles
            if profile.broker_account_fingerprint
        ]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("execution_profile_id values must be unique")
        if len(account_aliases) != len(set(account_aliases)):
            raise ValueError("account_alias values must be unique")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("broker_account_fingerprint values must be unique")
        return self


class BrokerPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_profile_id: str = Field(min_length=1)
    broker_account_fingerprint: str = Field(pattern=r"^[a-f0-9]{16}$")
    account_equity: float = Field(gt=0.0)
    buying_power: float = Field(ge=0.0)
    current_position_value: float = Field(ge=0.0)
    bid: float = Field(gt=0.0)
    ask: float = Field(gt=0.0)
    quote_at: AwareDatetime
    tradable: bool
    fractionable: bool
    regular_market_hours: bool

    @model_validator(mode="after")
    def require_ordered_quote(self) -> "BrokerPreflight":
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        return self


class LiveExecutionPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_packet_id: str = Field(min_length=1)
    order_intent_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    execution_profile_id: str = Field(min_length=1)
    agent_provider: AgentProvider
    account_alias: str = Field(min_length=1)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    ticker: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType
    target_weight: float = Field(ge=0.0, le=1.0)
    account_equity: float = Field(gt=0.0)
    current_position_value: float = Field(ge=0.0)
    notional: float = Field(gt=0.0)
    limit_price: float = Field(gt=0.0)
    quote_at: AwareDatetime
    spread_bps: float = Field(ge=0.0)
    require_human_approval: bool

    @model_validator(mode="after")
    def require_consistent_times(self) -> "LiveExecutionPacket":
        if self.quote_at > self.created_at:
            raise ValueError("quote_at cannot be after created_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self
