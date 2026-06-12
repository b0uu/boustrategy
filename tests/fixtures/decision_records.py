from datetime import UTC, datetime

from app.schemas.decision_record import InvestmentDecisionRecord


def valid_decision_record_data() -> dict:
    return {
        "decision_id": "dec_001",
        "created_at": datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        "ticker": "nvda",
        "asset_type": "EQUITY",
        "decision": "BUY",
        "theme_ids": ["ai_semiconductors"],
        "strategy_belief_ids": ["SB-002"],
        "trigger_id": "trig_001",
        "operating_mode": "CAPITAL_DEPLOYMENT",
        "regime_state": "GREEN",
        "source_pack_id": "sp_001",
        "initial_thesis": "AI infrastructure demand supports further upside.",
        "counter_thesis": "The market may already price in strong demand.",
        "adversarial_refinement": "Position size should respect valuation risk.",
        "refined_thesis": "NVDA remains a direct AI infrastructure exposure with strong momentum.",
        "what_is_priced_in": "Continued AI capex strength.",
        "thesis_invalidation_criteria": ["AI capex guidance weakens materially."],
        "add_conditions": ["Evidence improves while regime remains GREEN."],
        "trim_conditions": ["Position exceeds target weight."],
        "exit_conditions": ["Thesis is invalidated."],
        "proposed_target_weight": 0.12,
        "final_target_weight": 0.12,
        "source_claims": [
            {
                "claim": "Company demand is linked to AI infrastructure spending.",
                "source_ids": ["src_001"],
                "source_type": "COMPANY_IR",
                "source_timestamp": datetime(2026, 6, 10, 10, 0, tzinfo=UTC),
                "confidence": 0.8,
                "public_safe": True,
            }
        ],
        "x_signal_usage": {
            "used": False,
            "usage_type": "IRRELEVANT",
            "summary": "",
            "confirmed_outside_x": False,
        },
        "public_summary": "BUY decision passed schema validation.",
        "internal_notes": "",
        "order_intent_id": None,
        "broker_execution_record_id": None,
    }


def valid_decision_record() -> InvestmentDecisionRecord:
    return InvestmentDecisionRecord.model_validate(valid_decision_record_data())


def decision_record_with(**overrides) -> InvestmentDecisionRecord:
    data = valid_decision_record_data()
    data.update(overrides)
    return InvestmentDecisionRecord.model_validate(data)
