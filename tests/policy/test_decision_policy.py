from app.policy.decision_policy import PortfolioContext, evaluate_decision_policy
from tests.fixtures.decision_records import decision_record_with, valid_decision_record


def portfolio_context(**overrides: object) -> PortfolioContext:
    data: dict[str, object] = {
        "holdings_count": 5,
        "buy_add_trades_today": 0,
        "sell_trim_trades_today": 0,
    }
    data.update(overrides)
    return PortfolioContext.model_validate(data)


def test_valid_buy_in_green_is_approved():
    record = valid_decision_record()

    result = evaluate_decision_policy(record)

    assert result.approved
    assert result.reasons == []


def test_rejects_buy_in_red_regime():
    record = decision_record_with(regime_state="RED")

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "buy_or_add_in_red_requires_extraordinary_opportunity" in result.reasons


def test_rejects_buy_in_derisking_mode():
    record = decision_record_with(operating_mode="DE_RISKING")

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "buy_or_add_in_derisking_requires_extraordinary_opportunity" in result.reasons


def test_rejects_buy_without_invalidation_criteria():
    record = decision_record_with(thesis_invalidation_criteria=[])

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "missing_invalidation_criteria" in result.reasons


def test_rejects_buy_without_source_claims():
    record = decision_record_with(source_claims=[])

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "missing_source_claims" in result.reasons


def test_rejects_equity_target_weight_above_twenty_percent():
    record = decision_record_with(
        proposed_target_weight=0.25,
        final_target_weight=0.25,
    )

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "equity_target_weight_exceeds_limit" in result.reasons


def test_rejects_etf_target_weight_above_fifty_percent():
    record = decision_record_with(
        asset_type="ETF",
        proposed_target_weight=0.60,
        final_target_weight=0.60,
    )

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "etf_target_weight_exceeds_limit" in result.reasons


def test_rejects_buy_without_strategy_belief_mapping():
    record = decision_record_with(strategy_belief_ids=[])

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "missing_strategy_belief_mapping" in result.reasons


def test_rejects_x_used_without_outside_confirmation():
    record = decision_record_with(
        x_signal_usage={
            "used": True,
            "usage_type": "IDEA_SOURCE",
            "summary": "Curated X accounts flagged narrative acceleration.",
            "confirmed_outside_x": False,
        }
    )

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "x_signal_not_confirmed_outside_x" in result.reasons


def test_rejects_add_in_red_regime_without_escalation():
    record = decision_record_with(decision="ADD", regime_state="RED")

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "buy_or_add_in_red_requires_extraordinary_opportunity" in result.reasons


def test_rejects_add_in_derisking_mode_without_escalation():
    record = decision_record_with(decision="ADD", operating_mode="DE_RISKING")

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "buy_or_add_in_derisking_requires_extraordinary_opportunity" in result.reasons


def test_allows_extraordinary_buy_in_red_regime():
    record = decision_record_with(
        regime_state="RED",
        extraordinary_opportunity=True,
        extraordinary_justification=(
            "Panic selloff has disconnected price from intact AI capex evidence."
        ),
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_allows_extraordinary_add_in_derisking_mode():
    record = decision_record_with(
        decision="ADD",
        operating_mode="DE_RISKING",
        extraordinary_opportunity=True,
        extraordinary_justification=(
            "Panic selloff has disconnected price from intact AI capex evidence."
        ),
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_allows_hold_above_equity_weight_cap():
    record = decision_record_with(
        decision="HOLD",
        proposed_target_weight=0.25,
        final_target_weight=0.25,
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_allows_buy_at_exact_equity_weight_cap():
    record = decision_record_with(
        proposed_target_weight=0.20,
        final_target_weight=0.20,
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_allows_counter_thesis_x_usage_without_outside_confirmation():
    record = decision_record_with(
        decision="TRIM",
        x_signal_usage={
            "used": True,
            "usage_type": "COUNTER_THESIS",
            "summary": "skeptics flagged crowding",
            "confirmed_outside_x": False,
        },
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_allows_unconfirmed_x_on_non_actionable_decision():
    record = decision_record_with(
        decision="PASS",
        x_signal_usage={
            "used": True,
            "usage_type": "IDEA_SOURCE",
            "summary": "narrative velocity spike",
            "confirmed_outside_x": False,
        },
    )

    result = evaluate_decision_policy(record)

    assert result.approved


def test_rejects_buy_with_unconfirmed_x_confirmation_usage():
    record = decision_record_with(
        x_signal_usage={
            "used": True,
            "usage_type": "CONFIRMATION",
            "summary": "X confirmed the demand narrative",
            "confirmed_outside_x": False,
        },
    )

    result = evaluate_decision_policy(record)

    assert not result.approved
    assert "x_signal_not_confirmed_outside_x" in result.reasons


def test_rejects_buy_when_daily_buy_add_limit_reached():
    record = valid_decision_record()
    portfolio = portfolio_context(buy_add_trades_today=2)

    result = evaluate_decision_policy(record, portfolio)

    assert not result.approved
    assert "daily_buy_add_limit_reached" in result.reasons


def test_rejects_add_when_daily_buy_add_limit_reached():
    record = decision_record_with(decision="ADD")
    portfolio = portfolio_context(buy_add_trades_today=2)

    result = evaluate_decision_policy(record, portfolio)

    assert not result.approved
    assert "daily_buy_add_limit_reached" in result.reasons


def test_allows_sell_when_buy_add_limit_reached():
    record = decision_record_with(decision="SELL")
    portfolio = portfolio_context(buy_add_trades_today=2, sell_trim_trades_today=0)

    result = evaluate_decision_policy(record, portfolio)

    assert result.approved


def test_rejects_sell_when_circuit_breaker_tripped():
    record = decision_record_with(decision="SELL")
    portfolio = portfolio_context(sell_trim_trades_today=10)

    result = evaluate_decision_policy(record, portfolio)

    assert not result.approved
    assert "sell_trim_circuit_breaker_tripped" in result.reasons


def test_allows_hold_when_all_limits_reached():
    record = decision_record_with(decision="HOLD")
    portfolio = portfolio_context(
        buy_add_trades_today=2,
        sell_trim_trades_today=10,
        holdings_count=10,
    )

    result = evaluate_decision_policy(record, portfolio)

    assert result.approved


def test_rejects_buy_at_max_holdings():
    record = valid_decision_record()
    portfolio = portfolio_context(holdings_count=10)

    result = evaluate_decision_policy(record, portfolio)

    assert not result.approved
    assert "max_holdings_reached" in result.reasons


def test_allows_add_at_max_holdings():
    record = decision_record_with(decision="ADD")
    portfolio = portfolio_context(holdings_count=10)

    result = evaluate_decision_policy(record, portfolio)

    assert result.approved


def test_rejects_buy_exceeding_primary_theme_cap():
    record = valid_decision_record()
    portfolio = portfolio_context(primary_theme_weights={"ai_semiconductors": 0.55})

    result = evaluate_decision_policy(record, portfolio)

    assert not result.approved
    assert "primary_theme_concentration_exceeded" in result.reasons


def test_allows_buy_within_primary_theme_cap():
    record = valid_decision_record()
    portfolio = portfolio_context(primary_theme_weights={"ai_semiconductors": 0.40})

    result = evaluate_decision_policy(record, portfolio)

    assert result.approved


def test_portfolio_rules_skipped_without_context():
    record = valid_decision_record()

    result = evaluate_decision_policy(record)

    assert result.approved
