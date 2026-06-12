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
