"""Reporting facts are separate from execution permissions and preflight."""

from datetime import date
from decimal import Decimal, localcontext
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

Money = Annotated[Decimal, Field(max_digits=24, decimal_places=2, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=40, decimal_places=18, allow_inf_nan=False)]
Price = Annotated[Decimal, Field(ge=0, max_digits=40, decimal_places=18, allow_inf_nan=False)]


class ReportingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportingPosition(ReportingModel):
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    quantity: Quantity | None = None
    market_value: Money | None = Field(default=None, ge=0)
    average_cost: Price | None = None
    price: Price | None = None
    quote_at: AwareDatetime | None = None
    price_quality: Literal["current", "stale", "missing"] = "missing"
    name: str | None = Field(default=None, max_length=200)
    theme: str | None = Field(default=None, max_length=100)
    asset_class: Literal["equity", "etf", "fixed_income", "other", "unknown"] = "unknown"

    @model_validator(mode="after")
    def consistent_price(self) -> "ReportingPosition":
        with localcontext() as context:
            context.prec = 100
            if self.price_quality == "current" and (self.price is None or self.quote_at is None):
                raise ValueError("current prices require price and quote_at")
            if (
                self.quantity is not None
                and self.price is not None
                and self.market_value is not None
            ):
                if (self.quantity * self.price).quantize(Decimal("0.01")) != self.market_value:
                    raise ValueError("position value does not equal rounded quantity times price")
            return self


class Observation(ReportingModel):
    observation_id: str = Field(min_length=1, max_length=200)
    external_event_id: str = Field(min_length=1, max_length=200)
    mode: Literal["live", "paper"]
    account_id: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    sequence: int = Field(default=0, ge=0)
    supersedes: str | None = None
    voided: bool = False
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def consistent_identity(self) -> "Observation":
        if self.supersedes == self.observation_id:
            raise ValueError("an observation cannot supersede itself")
        if self.mode == "live" and (
            len(self.account_id) != 16 or any(c not in "0123456789abcdef" for c in self.account_id)
        ):
            raise ValueError("live account_id must be the broker account fingerprint")
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at")
        if self.voided and self.supersedes is None:
            raise ValueError("voided observations must correct an existing observation")
        return self


class ValuationObservation(Observation):
    kind: Literal["valuation"] = "valuation"
    equity: Money | None = Field(default=None, ge=0)
    cash: Money | None = None
    receivables: Money = Decimal("0")
    liabilities: Money = Field(default=Decimal("0"), ge=0)
    positions: list[ReportingPosition] | None = None
    complete: bool = False
    phase: Literal["session_close", "intraday", "before_flow", "after_flow"] = "intraday"
    session_date: date | None = None
    previous_session_date: date | None = None

    @model_validator(mode="after")
    def reconcile_balance(self) -> "ValuationObservation":
        with localcontext() as context:
            context.prec = 100
            if self.phase == "session_close" and self.session_date is None:
                raise ValueError("session close requires a session date")
            if self.previous_session_date and (
                self.session_date is None or self.previous_session_date >= self.session_date
            ):
                raise ValueError("previous session must precede session date")
            if self.positions is not None:
                tickers = [p.ticker for p in self.positions]
                if len(set(tickers)) != len(tickers):
                    raise ValueError("valuation tickers must be unique")
                if any(p.quote_at and p.quote_at > self.occurred_at for p in self.positions):
                    raise ValueError("quotes cannot follow valuation time")
            if self.complete:
                if self.equity is None or self.cash is None or self.positions is None:
                    raise ValueError("complete valuation requires equity, cash and positions")
                if any(
                    p.market_value is None or p.price_quality != "current" for p in self.positions
                ):
                    raise ValueError("complete valuation requires current position values")
                total = (
                    self.cash
                    + self.receivables
                    - self.liabilities
                    + sum(
                        (p.market_value for p in self.positions if p.market_value is not None),
                        Decimal(0),
                    )
                )
                if total != self.equity:
                    raise ValueError("complete balance does not reconcile")
            return self


class FlowObservation(Observation):
    kind: Literal["flow"] = "flow"
    flow_type: Literal["deposit", "withdrawal", "transfer_in", "transfer_out"]
    amount: Money
    before_valuation_id: str | None = None
    after_valuation_id: str | None = None

    @model_validator(mode="after")
    def consistent_flow(self) -> "FlowObservation":
        if self.amount == 0 or (self.amount > 0) != (self.flow_type in {"deposit", "transfer_in"}):
            raise ValueError("external flow amount has the wrong sign")
        if (
            self.before_valuation_id is not None
            and self.before_valuation_id == self.after_valuation_id
        ):
            raise ValueError("flow boundaries must be distinct")
        return self


class FillObservation(Observation):
    kind: Literal["fill"] = "fill"
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    side: Literal["BUY", "SELL"]
    quantity: Quantity = Field(gt=0)
    price: Price = Field(gt=0)
    gross_notional: Money = Field(gt=0)
    fee: Money | None = Field(default=None, ge=0)
    origin: Literal["agent", "external"]
    decision_id: str | None = None
    order_external_id: str | None = None
    order_state: Literal["partially_filled", "filled", "canceled"] = "filled"
    canceled_quantity: Quantity = Decimal(0)
    settled_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def consistent_fill(self) -> "FillObservation":
        with localcontext() as context:
            context.prec = 100
            if (self.quantity * self.price).quantize(Decimal("0.01")) != self.gross_notional:
                raise ValueError("fill notional must match rounded quantity times price")
            if (self.origin == "agent") != (self.decision_id is not None):
                raise ValueError("only agent fills require a decision link")
            if self.canceled_quantity and self.order_state != "canceled":
                raise ValueError("canceled remainder requires canceled order state")
            if self.settled_at and self.settled_at < self.occurred_at:
                raise ValueError("settlement cannot precede fill")
            return self


class CorporateActionObservation(Observation):
    kind: Literal["corporate_action"] = "corporate_action"
    action: Literal["dividend", "fee", "split", "transfer_in", "transfer_out"]
    ticker: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    amount: Money | None = None
    quantity: Quantity | None = None
    split_ratio: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)] | None = None
    flow_external_id: str | None = None

    @model_validator(mode="after")
    def consistent_action(self) -> "CorporateActionObservation":
        if self.action in {"dividend", "fee"}:
            if (
                self.amount is None
                or self.amount <= 0
                or self.quantity is not None
                or self.split_ratio is not None
            ):
                raise ValueError("dividend/fee requires a positive cash amount only")
        elif self.action == "split":
            if (
                self.ticker is None
                or self.split_ratio is None
                or self.amount is not None
                or self.quantity is not None
            ):
                raise ValueError("split requires ticker and ratio only")
        elif (
            self.ticker is None
            or self.quantity is None
            or self.quantity <= 0
            or self.flow_external_id is None
            or self.split_ratio is not None
        ):
            raise ValueError("security transfer requires ticker, quantity and linked external flow")
        return self


class CoverageObservation(Observation):
    kind: Literal["coverage"] = "coverage"
    start_at: AwareDatetime
    end_at: AwareDatetime
    external_flows_complete: bool = False
    activity_complete: bool = False

    @model_validator(mode="after")
    def consistent_coverage(self) -> "CoverageObservation":
        if self.start_at >= self.end_at or self.end_at > self.occurred_at:
            raise ValueError("coverage must describe an observed positive interval")
        return self


ReportingObservation = Annotated[
    ValuationObservation
    | FlowObservation
    | FillObservation
    | CorporateActionObservation
    | CoverageObservation,
    Field(discriminator="kind"),
]
OBSERVATION_ADAPTER: TypeAdapter[ReportingObservation] = TypeAdapter(ReportingObservation)
