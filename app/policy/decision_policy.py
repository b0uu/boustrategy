from pydantic import BaseModel, Field

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
_EXPOSURE_INCREASING = {Decision.BUY, Decision.ADD}


class PolicyResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    adjusted_final_target_weight: float | None = None


def evaluate_decision_policy(record: InvestmentDecisionRecord) -> PolicyResult:
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

    return PolicyResult(approved=not reasons, reasons=reasons)


def _is_actionable(record: InvestmentDecisionRecord) -> bool:
    return record.decision in {
        Decision.BUY,
        Decision.ADD,
        Decision.TRIM,
        Decision.SELL,
    }
