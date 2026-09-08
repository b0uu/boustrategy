"""Human labels and categories for the rules actually evaluated in code."""

from app.schemas.policy_reporting import RuleDefinition

MAX_EQUITY_TARGET_WEIGHT = 0.20
MAX_ETF_TARGET_WEIGHT = 0.50
MAX_BUY_ADD_TRADES_PER_DAY = 2
MAX_BUY_ADD_TRADES_PER_DAY_BRAKE = 5
MAX_SELL_TRIM_TRADES_PER_DAY = 10
MAX_HOLDINGS = 10
MAX_PRIMARY_THEME_WEIGHT = 0.60

POLICY_VERSION = "decision-policy-1"
VALIDATOR_VERSION = "decision-record-public-1"

RULE_LABELS = {
    "regime_state_mismatch": "The decision's regime differs from the recorded regime.",
    "buy_or_add_in_red_requires_extraordinary_opportunity": (
        "Increasing exposure in RED requires an extraordinary-opportunity exception."
    ),
    "buy_or_add_in_derisking_requires_extraordinary_opportunity": (
        "Increasing exposure while de-risking requires an extraordinary-opportunity exception."
    ),
    "equity_target_weight_exceeds_limit": "The proposed equity position exceeds the entry limit.",
    "etf_target_weight_exceeds_limit": "The proposed ETF position exceeds the entry limit.",
    "missing_strategy_belief_mapping": "Increasing exposure requires a strategy-belief mapping.",
    "missing_invalidation_criteria": "An actionable decision needs thesis-invalidation criteria.",
    "missing_source_claims": "An actionable decision needs source claims.",
    "x_signal_not_confirmed_outside_x": (
        "Thesis-supporting X evidence needs confirmation outside X."
    ),
    "buy_add_circuit_breaker_tripped": (
        "The daily risk-increasing trade circuit breaker is reached."
    ),
    "daily_buy_add_limit_reached": "The daily risk-increasing trade limit needs an exception.",
    "sell_trim_circuit_breaker_tripped": "The daily sell/trim circuit breaker is reached.",
    "max_holdings_reached": "A new holding would exceed the holding-count limit.",
    "primary_theme_concentration_exceeded": "The proposed theme exposure exceeds the entry limit.",
}


RULES = {
    rule_id: RuleDefinition(
        rule_id=rule_id,
        name=name,
        failure_explanation=RULE_LABELS[rule_id],
        threshold=threshold,
        comparator=comparator,
        unit=unit,
        scope=scope,
    )
    for rule_id, name, threshold, comparator, unit, scope in (
        ("regime_state_mismatch", "Regime consistency", None, "eq", "regime", "decision"),
        (
            "buy_or_add_in_red_requires_extraordinary_opportunity",
            "RED exposure exception",
            True,
            "eq",
            "boolean",
            "decision",
        ),
        (
            "buy_or_add_in_derisking_requires_extraordinary_opportunity",
            "De-risking exposure exception",
            True,
            "eq",
            "boolean",
            "decision",
        ),
        (
            "equity_target_weight_exceeds_limit",
            "Equity entry concentration",
            MAX_EQUITY_TARGET_WEIGHT,
            "lte",
            "fraction",
            "proposal",
        ),
        (
            "etf_target_weight_exceeds_limit",
            "ETF entry concentration",
            MAX_ETF_TARGET_WEIGHT,
            "lte",
            "fraction",
            "proposal",
        ),
        (
            "missing_strategy_belief_mapping",
            "Strategy-belief mapping",
            1,
            "gte",
            "count",
            "decision",
        ),
        (
            "missing_invalidation_criteria",
            "Thesis-invalidation criteria",
            1,
            "gte",
            "count",
            "decision",
        ),
        ("missing_source_claims", "Source claims", 1, "gte", "count", "decision"),
        (
            "x_signal_not_confirmed_outside_x",
            "Independent X confirmation",
            True,
            "eq",
            "boolean",
            "decision",
        ),
        (
            "buy_add_circuit_breaker_tripped",
            "Risk-increasing trade circuit breaker",
            MAX_BUY_ADD_TRADES_PER_DAY_BRAKE,
            "lt",
            "count",
            "portfolio",
        ),
        (
            "daily_buy_add_limit_reached",
            "Ordinary risk-increasing trade limit",
            MAX_BUY_ADD_TRADES_PER_DAY,
            "lt",
            "count",
            "portfolio",
        ),
        (
            "sell_trim_circuit_breaker_tripped",
            "Sell/trim circuit breaker",
            MAX_SELL_TRIM_TRADES_PER_DAY,
            "lt",
            "count",
            "portfolio",
        ),
        ("max_holdings_reached", "New holding capacity", MAX_HOLDINGS, "lt", "count", "portfolio"),
        (
            "primary_theme_concentration_exceeded",
            "Theme entry concentration",
            MAX_PRIMARY_THEME_WEIGHT,
            "lte",
            "fraction",
            "proposal",
        ),
    )
}


def catalog() -> dict[str, object]:
    return {
        "version": POLICY_VERSION,
        "history": [
            {
                "version": POLICY_VERSION,
                "change": (
                    "First recorded evaluation version; existing enforcement thresholds retained."
                ),
                "effective_from": None,
            }
        ],
        "decision_rules": [
            {**rule.model_dump(), "version": POLICY_VERSION, "category": "decision_policy"}
            for rule in RULES.values()
        ],
        "posture": [
            {
                "rule_id": "initial_position_guidance",
                "name": "Initial position sizing",
                "description": "Posture guidance, not a deterministic approval gate.",
                "category": "posture",
                "evaluated": False,
            }
        ],
        "execution_controls": [
            {
                "rule_id": rule,
                "name": label,
                "category": "execution_control",
                "evaluated_by_decision_policy": False,
                "threshold": None,
                "threshold_source": "execution_profile_or_preflight",
            }
            for rule, label in (
                ("account_binding", "Account-bound broker preflight"),
                ("quote_freshness", "Quote freshness"),
                ("spread", "Bid/ask spread"),
                ("order_notional", "Order notional"),
                ("execution_profile_enablement", "Execution profile enablement"),
            )
        ],
    }
