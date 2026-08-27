from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.reasoning_run import ReasoningRun


def _run_data() -> dict[str, object]:
    return {
        "reasoning_run_id": "rr_2026-08-27_close_codex",
        "session_date": date(2026, 8, 27),
        "slot": "close",
        "execution_profile_id": "codex",
        "model_label": "Codex",
        "shared_bundle_path": "data/reason/2026-08-27/shared_bundle.md",
        "shared_bundle_sha256": "a" * 64,
        "portfolio_snapshot_id": "snap_codex",
        "started_at": datetime(2026, 8, 27, 20, tzinfo=UTC),
        "result": "PREPARED",
    }


def test_prepared_reasoning_run_is_valid() -> None:
    assert ReasoningRun.model_validate(_run_data()).result == "PREPARED"


@pytest.mark.parametrize(
    "updates",
    [
        {"shared_bundle_sha256": "A" * 64},
        {"completed_at": datetime(2026, 8, 27, 21, tzinfo=UTC)},
        {"result": "NO_ACTION"},
        {
            "result": "NO_ACTION",
            "completed_at": datetime(2026, 8, 27, 21, tzinfo=UTC),
            "public_summary": "No action.",
            "decision_ids": ["d1"],
        },
        {
            "result": "DECISIONS_AUTHORED",
            "completed_at": datetime(2026, 8, 27, 21, tzinfo=UTC),
            "public_summary": "One decision.",
        },
    ],
)
def test_reasoning_run_rejects_inconsistent_content(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReasoningRun.model_validate({**_run_data(), **updates})
