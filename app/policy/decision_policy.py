from pydantic import BaseModel, Field

from app.policy.catalog import (
    MAX_BUY_ADD_TRADES_PER_DAY,
    MAX_BUY_ADD_TRADES_PER_DAY_BRAKE,
    MAX_EQUITY_TARGET_WEIGHT,
    MAX_ETF_TARGET_WEIGHT,
    MAX_HOLDINGS,
    MAX_PRIMARY_THEME_WEIGHT,
    MAX_SELL_TRIM_TRADES_PER_DAY,
    POLICY_VERSION,
    RULES,
)
from app.schemas.decision_record import (
    AssetType,
    Decision,
    InvestmentDecisionRecord,
    OperatingMode,
    RegimeState,
    XSignalUsageType,
)
from app.schemas.policy_reporting import PortfolioInputs, RuleCheck

PortfolioContext = PortfolioInputs

_EXPOSURE_INCREASING = {Decision.BUY, Decision.ADD}


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    checks: list[RuleCheck] = Field(default_factory=list)


def evaluate_decision_policy(
    record: InvestmentDecisionRecord,
    portfolio: PortfolioContext | None = None,
    true_regime_state: RegimeState | None = None,
) -> PolicyResult:
    checks: list[RuleCheck] = []
    increasing = record.decision in _EXPOSURE_INCREASING
    actionable = record.decision in {Decision.BUY, Decision.ADD, Decision.TRIM, Decision.SELL}

    def check(
        rule_id: str,
        *,
        applicable: bool,
        observed: float | int | bool | str | None,
        passed: bool,
        missing: bool = False,
    ) -> None:
        definition = RULES[rule_id]
        threshold = (
            true_regime_state.value
            if rule_id == "regime_state_mismatch" and true_regime_state
            else definition.threshold
        )
        comparator, unit, scope = definition.comparator, definition.unit, definition.scope
        result = (
            "not_applicable"
            if not applicable
            else "missing_input"
            if missing
            else "passed"
            if passed
            else "failed"
        )
        headroom = None
        if (
            result in {"passed", "failed"}
            and unit in {"fraction", "count"}
            and isinstance(observed, int | float)
            and isinstance(threshold, int | float)
        ):
            headroom = threshold - observed if comparator in {"lt", "lte"} else observed - threshold
        checks.append(
            RuleCheck(
                name=definition.name,
                failure_explanation=definition.failure_explanation,
                rule_id=rule_id,
                version=POLICY_VERSION,
                scope=scope,
                result=result,
                observed=observed if applicable and not missing else None,
                threshold=threshold,
                comparator=comparator,
                unit=unit,
                headroom=headroom,
            )
        )

    check(
        "regime_state_mismatch",
        applicable=True,
        observed=record.regime_state.value,
        passed=record.regime_state == true_regime_state,
        missing=true_regime_state is None,
    )
    check(
        "buy_or_add_in_red_requires_extraordinary_opportunity",
        applicable=increasing and record.regime_state == RegimeState.RED,
        observed=record.extraordinary_opportunity,
        passed=record.extraordinary_opportunity,
    )
    check(
        "buy_or_add_in_derisking_requires_extraordinary_opportunity",
        applicable=increasing and record.operating_mode == OperatingMode.DE_RISKING,
        observed=record.extraordinary_opportunity,
        passed=record.extraordinary_opportunity,
    )
    check(
        "equity_target_weight_exceeds_limit",
        applicable=increasing and record.asset_type == AssetType.EQUITY,
        observed=record.final_target_weight,
        passed=record.final_target_weight <= MAX_EQUITY_TARGET_WEIGHT,
    )
    check(
        "etf_target_weight_exceeds_limit",
        applicable=increasing and record.asset_type == AssetType.ETF,
        observed=record.final_target_weight,
        passed=record.final_target_weight <= MAX_ETF_TARGET_WEIGHT,
    )
    check(
        "missing_strategy_belief_mapping",
        applicable=increasing,
        observed=len(record.strategy_belief_ids),
        passed=bool(record.strategy_belief_ids),
    )
    check(
        "missing_invalidation_criteria",
        applicable=actionable,
        observed=len(record.thesis_invalidation_criteria),
        passed=bool(record.thesis_invalidation_criteria),
    )
    check(
        "missing_source_claims",
        applicable=actionable,
        observed=len(record.source_claims),
        passed=bool(record.source_claims),
    )
    supporting_x = record.x_signal_usage.usage_type in {
        XSignalUsageType.IDEA_SOURCE,
        XSignalUsageType.CONFIRMATION,
    }
    check(
        "x_signal_not_confirmed_outside_x",
        applicable=actionable and record.x_signal_usage.used and supporting_x,
        observed=record.x_signal_usage.confirmed_outside_x,
        passed=record.x_signal_usage.confirmed_outside_x,
    )
    buy_count = portfolio.buy_add_trades_today if portfolio else None
    brake = buy_count is not None and buy_count >= MAX_BUY_ADD_TRADES_PER_DAY_BRAKE
    check(
        "buy_add_circuit_breaker_tripped",
        applicable=increasing,
        observed=buy_count,
        passed=not brake,
        missing=portfolio is None,
    )
    check(
        "daily_buy_add_limit_reached",
        applicable=increasing and not brake and not record.extraordinary_opportunity,
        observed=buy_count,
        passed=buy_count is not None and buy_count < MAX_BUY_ADD_TRADES_PER_DAY,
        missing=portfolio is None,
    )
    sell_count = portfolio.sell_trim_trades_today if portfolio else None
    check(
        "sell_trim_circuit_breaker_tripped",
        applicable=record.decision in {Decision.TRIM, Decision.SELL},
        observed=sell_count,
        passed=sell_count is not None and sell_count < MAX_SELL_TRIM_TRADES_PER_DAY,
        missing=portfolio is None,
    )
    holdings = portfolio.holdings_count if portfolio else None
    check(
        "max_holdings_reached",
        applicable=record.decision == Decision.BUY,
        observed=holdings,
        passed=holdings is not None and holdings < MAX_HOLDINGS,
        missing=portfolio is None,
    )
    # Context maps the complete other-position theme weights; absent themes have zero exposure.
    theme_weight = (
        portfolio.primary_theme_weights.get(record.primary_theme_id or "", 0.0)
        + record.final_target_weight
        if portfolio
        else None
    )
    check(
        "primary_theme_concentration_exceeded",
        applicable=increasing and record.primary_theme_id is not None,
        observed=theme_weight,
        passed=theme_weight is not None and not (theme_weight > MAX_PRIMARY_THEME_WEIGHT),
        missing=portfolio is None,
    )
    reasons = [item.rule_id for item in checks if item.result == "failed"]
    return PolicyResult(approved=not reasons, reasons=reasons, checks=checks)
