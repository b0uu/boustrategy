from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.decision_record import InvestmentDecisionRecord
from tests.fixtures.decision_records import valid_decision_record_data


def test_valid_buy_record_passes_validation():
    record = InvestmentDecisionRecord.model_validate(valid_decision_record_data())

    assert record.decision == "BUY"
    assert record.ticker == "NVDA"


def test_unknown_decision_fails_validation():
    data = valid_decision_record_data()
    data["decision"] = "GO_BIG"

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_unknown_regime_state_fails_validation():
    data = valid_decision_record_data()
    data["regime_state"] = "SUPER_GREEN"

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_final_target_weight_cannot_exceed_proposed_target_weight():
    data = valid_decision_record_data()
    data["proposed_target_weight"] = 0.10
    data["final_target_weight"] = 0.12

    with pytest.raises(ValidationError, match="final_target_weight"):
        InvestmentDecisionRecord.model_validate(data)


def test_actionable_decision_requires_refined_thesis():
    data = valid_decision_record_data()
    data["refined_thesis"] = ""

    with pytest.raises(ValidationError, match="refined_thesis"):
        InvestmentDecisionRecord.model_validate(data)


def test_non_actionable_decision_does_not_require_refined_thesis():
    data = valid_decision_record_data()
    data["decision"] = "WATCHLIST"
    data["refined_thesis"] = ""
    data["final_target_weight"] = 0.0
    data["proposed_target_weight"] = 0.0

    record = InvestmentDecisionRecord.model_validate(data)

    assert record.decision == "WATCHLIST"


CONDITIONS = {"cover_below": 150.0, "stop_above": 260.0, "review_by": "2026-06-30"}


def short_watchlist_data(**overrides: object) -> dict[str, object]:
    data = valid_decision_record_data()
    data.update(
        decision="SHORT_WATCHLIST",
        counter_thesis="Bull case: backlog could re-accelerate.",
        what_is_priced_in="Consensus still prices a second-half recovery.",
        proposed_target_weight=0.0,
        final_target_weight=0.0,
        short_removal_conditions=dict(CONDITIONS),
    )
    data.update(overrides)
    return data


def test_short_watchlist_records_a_researched_short_with_no_weight():
    record = InvestmentDecisionRecord.model_validate(short_watchlist_data())

    assert record.decision == "SHORT_WATCHLIST"
    assert record.short_removal_conditions is not None
    assert record.short_removal_conditions.review_by.isoformat() == "2026-06-30"


def test_a_short_call_needs_removal_conditions_that_bracket_its_price():
    with pytest.raises(ValidationError, match="requires short_removal_conditions"):
        InvestmentDecisionRecord.model_validate(short_watchlist_data(short_removal_conditions=None))
    with pytest.raises(ValidationError, match="cover_below must be under stop_above"):
        InvestmentDecisionRecord.model_validate(
            short_watchlist_data(
                short_removal_conditions={**CONDITIONS, "cover_below": 300.0},
            )
        )
    with pytest.raises(ValidationError, match="must sit between"):
        InvestmentDecisionRecord.model_validate(
            short_watchlist_data(reference_price=140.0, reference_price_at="2026-06-10T11:00:00Z")
        )
    with pytest.raises(ValidationError, match="review_by must follow"):
        InvestmentDecisionRecord.model_validate(
            short_watchlist_data(short_removal_conditions={**CONDITIONS, "review_by": "2026-06-09"})
        )


def test_only_a_short_call_carries_removal_conditions():
    data = valid_decision_record_data()
    data["short_removal_conditions"] = dict(CONDITIONS)

    with pytest.raises(ValidationError, match="belong only to a SHORT_WATCHLIST"):
        InvestmentDecisionRecord.model_validate(data)


def test_short_watchlist_cannot_carry_weight():
    data = short_watchlist_data()
    data.update(proposed_target_weight=0.12, final_target_weight=0.12)

    with pytest.raises(ValidationError, match="target weights must be 0"):
        InvestmentDecisionRecord.model_validate(data)


def test_short_watchlist_requires_a_counter_thesis():
    with pytest.raises(ValidationError, match="counter_thesis"):
        InvestmentDecisionRecord.model_validate(short_watchlist_data(counter_thesis=""))


def test_short_removal_must_give_its_reason():
    data = valid_decision_record_data()
    data.update(
        decision="SHORT_WATCHLIST_REMOVE",
        refined_thesis="",
        proposed_target_weight=0.0,
        final_target_weight=0.0,
    )

    with pytest.raises(ValidationError, match="SHORT_WATCHLIST_REMOVE"):
        InvestmentDecisionRecord.model_validate(data)


def test_x_usage_requires_summary_when_used():
    data = valid_decision_record_data()
    data["x_signal_usage"] = {
        "used": True,
        "usage_type": "IDEA_SOURCE",
        "summary": "",
        "confirmed_outside_x": False,
    }

    with pytest.raises(ValidationError, match="x_signal_usage.summary"):
        InvestmentDecisionRecord.model_validate(data)


def test_source_claim_confidence_must_be_between_zero_and_one():
    data = valid_decision_record_data()
    data["source_claims"][0]["confidence"] = 1.2

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_whitespace_only_ticker_fails_validation():
    data = valid_decision_record_data()
    data["ticker"] = "   "

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_ticker_with_invalid_characters_fails_validation():
    data = valid_decision_record_data()
    data["ticker"] = "NV DA"

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_ticker_with_share_class_punctuation_passes():
    data = valid_decision_record_data()
    data["ticker"] = "brk.b"

    record = InvestmentDecisionRecord.model_validate(data)

    assert record.ticker == "BRK.B"


def test_naive_created_at_fails_validation():
    data = valid_decision_record_data()
    data["created_at"] = datetime(2026, 6, 10, 12, 0)

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_naive_source_timestamp_fails_validation():
    data = valid_decision_record_data()
    data["source_claims"][0]["source_timestamp"] = datetime(2026, 6, 10, 12, 0)

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_unknown_source_type_fails_validation():
    data = valid_decision_record_data()
    data["source_claims"][0]["source_type"] = "BLOG"

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_x_usage_used_with_irrelevant_type_fails_validation():
    data = valid_decision_record_data()
    data["x_signal_usage"] = {
        "used": True,
        "usage_type": "IRRELEVANT",
        "summary": "something",
        "confirmed_outside_x": False,
    }

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_x_usage_not_used_with_active_type_fails_validation():
    data = valid_decision_record_data()
    data["x_signal_usage"] = {
        "used": False,
        "usage_type": "IDEA_SOURCE",
        "summary": "",
        "confirmed_outside_x": False,
    }

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_x_usage_not_used_with_outside_confirmation_fails_validation():
    data = valid_decision_record_data()
    data["x_signal_usage"] = {
        "used": False,
        "usage_type": "IRRELEVANT",
        "summary": "",
        "confirmed_outside_x": True,
    }

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_extraordinary_opportunity_requires_justification():
    data = valid_decision_record_data()
    data["extraordinary_opportunity"] = True
    data["extraordinary_justification"] = "  "

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_primary_theme_must_be_listed_in_theme_ids():
    data = valid_decision_record_data()
    data["primary_theme_id"] = "data_centers"

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_buy_requires_primary_theme():
    data = valid_decision_record_data()
    data.pop("primary_theme_id")

    with pytest.raises(ValidationError):
        InvestmentDecisionRecord.model_validate(data)


def test_watchlist_does_not_require_primary_theme():
    data = valid_decision_record_data()
    data["decision"] = "WATCHLIST"
    data["proposed_target_weight"] = 0.0
    data["final_target_weight"] = 0.0
    data.pop("primary_theme_id")

    record = InvestmentDecisionRecord.model_validate(data)

    assert record.decision == "WATCHLIST"
