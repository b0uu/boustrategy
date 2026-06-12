from pydantic import BaseModel, Field

from app.schemas.decision_record import AssetType, Decision, InvestmentDecisionRecord, OperatingMode, RegimeState


MAX_EQUITY_TARGET_WEIGHT = 0.20
MAX_ETF_TARGET_WEIGHT = 0.50


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    adjusted_final_target_weight: float | None = None


def evaluate_decision_policy(record: InvestmentDecisionRecord) -> PolicyResult:
    reasons: list[str] = []

    if record.decision == Decision.BUY and record.regime_state == RegimeState.RED:
        reasons.append("buy_disallowed_in_red_regime")

    if record.decision == Decision.BUY and record.operating_mode == OperatingMode.DE_RISKING:
        reasons.append("buy_disallowed_in_derisking_mode")

    if (
        record.asset_type == AssetType.EQUITY
        and record.final_target_weight > MAX_EQUITY_TARGET_WEIGHT
    ):
        reasons.append("equity_target_weight_exceeds_limit")

    if record.asset_type == AssetType.ETF and record.final_target_weight > MAX_ETF_TARGET_WEIGHT:
        reasons.append("etf_target_weight_exceeds_limit")

    if record.decision in {Decision.BUY, Decision.ADD} and not record.strategy_belief_ids:
        reasons.append("missing_strategy_belief_mapping")

    if _is_actionable(record) and not record.thesis_invalidation_criteria:
        reasons.append("missing_invalidation_criteria")

    if _is_actionable(record) and not record.source_claims:
        reasons.append("missing_source_claims")

    if record.x_signal_usage.used and not record.x_signal_usage.confirmed_outside_x:
        reasons.append("x_signal_not_confirmed_outside_x")

    return PolicyResult(approved=not reasons, reasons=reasons)


def _is_actionable(record: InvestmentDecisionRecord) -> bool:
    return record.decision in {
        Decision.BUY,
        Decision.ADD,
        Decision.TRIM,
        Decision.SELL,
    }
