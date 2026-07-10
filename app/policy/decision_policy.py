from pydantic import BaseModel, ConfigDict, Field

from app.schemas.decision_record import (
    AssetType,
    Decision,
    InvestmentDecisionRecord,
    OperatingMode,
    RegimeState,
    XSignalUsageType,
)


MAX_EQUITY_TARGET_WEIGHT = 0.20
MAX_ETF_TARGET_WEIGHT = 0.50
MAX_BUY_ADD_TRADES_PER_DAY = 2
MAX_SELL_TRIM_TRADES_PER_DAY = 10
MAX_HOLDINGS = 10
MAX_PRIMARY_THEME_WEIGHT = 0.60
_EXPOSURE_INCREASING = {Decision.BUY, Decision.ADD}


class PortfolioContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings_count: int = Field(ge=0)
    buy_add_trades_today: int = Field(ge=0)
    sell_trim_trades_today: int = Field(ge=0)
    # Weight excludes an existing position in the evaluated ticker to avoid double-counting ADDs.
    primary_theme_weights: dict[str, float] = Field(default_factory=dict)


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)


def evaluate_decision_policy(
    record: InvestmentDecisionRecord,
    portfolio: PortfolioContext | None = None,
) -> PolicyResult:
    reasons: list[str] = []

    if (
        record.decision in _EXPOSURE_INCREASING
        and record.regime_state == RegimeState.RED
        and not record.extraordinary_opportunity
    ):
        reasons.append("buy_or_add_in_red_requires_extraordinary_opportunity")

    if (
        record.decision in _EXPOSURE_INCREASING
        and record.operating_mode == OperatingMode.DE_RISKING
        and not record.extraordinary_opportunity
    ):
        reasons.append("buy_or_add_in_derisking_requires_extraordinary_opportunity")

    if (
        record.decision in _EXPOSURE_INCREASING
        and record.asset_type == AssetType.EQUITY
        and record.final_target_weight > MAX_EQUITY_TARGET_WEIGHT
    ):
        reasons.append("equity_target_weight_exceeds_limit")

    if (
        record.decision in _EXPOSURE_INCREASING
        and record.asset_type == AssetType.ETF
        and record.final_target_weight > MAX_ETF_TARGET_WEIGHT
    ):
        reasons.append("etf_target_weight_exceeds_limit")

    if record.decision in {Decision.BUY, Decision.ADD} and not record.strategy_belief_ids:
        reasons.append("missing_strategy_belief_mapping")

    if _is_actionable(record) and not record.thesis_invalidation_criteria:
        reasons.append("missing_invalidation_criteria")

    if _is_actionable(record) and not record.source_claims:
        reasons.append("missing_source_claims")

    thesis_supporting_x = record.x_signal_usage.usage_type in {
        XSignalUsageType.IDEA_SOURCE,
        XSignalUsageType.CONFIRMATION,
    }
    if (
        _is_actionable(record)
        and record.x_signal_usage.used
        and thesis_supporting_x
        and not record.x_signal_usage.confirmed_outside_x
    ):
        reasons.append("x_signal_not_confirmed_outside_x")

    if portfolio is not None:
        if (
            record.decision in _EXPOSURE_INCREASING
            and portfolio.buy_add_trades_today >= MAX_BUY_ADD_TRADES_PER_DAY
        ):
            reasons.append("daily_buy_add_limit_reached")

        if (
            record.decision in {Decision.TRIM, Decision.SELL}
            and portfolio.sell_trim_trades_today >= MAX_SELL_TRIM_TRADES_PER_DAY
        ):
            reasons.append("sell_trim_circuit_breaker_tripped")

        if record.decision == Decision.BUY and portfolio.holdings_count >= MAX_HOLDINGS:
            reasons.append("max_holdings_reached")

        if (
            record.decision in _EXPOSURE_INCREASING
            and record.primary_theme_id is not None
            and portfolio.primary_theme_weights.get(record.primary_theme_id, 0.0)
            + record.final_target_weight
            > MAX_PRIMARY_THEME_WEIGHT
        ):
            reasons.append("primary_theme_concentration_exceeded")

    return PolicyResult(approved=not reasons, reasons=reasons)


def _is_actionable(record: InvestmentDecisionRecord) -> bool:
    return record.decision in {
        Decision.BUY,
        Decision.ADD,
        Decision.TRIM,
        Decision.SELL,
    }
