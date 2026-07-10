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
