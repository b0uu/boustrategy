import re
from datetime import date
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ReasoningRunResult(StrEnum):
    PREPARED = "PREPARED"
    NO_ACTION = "NO_ACTION"
    DECISIONS_AUTHORED = "DECISIONS_AUTHORED"
    FAILED = "FAILED"


class ReasoningRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning_run_id: str = Field(min_length=1)
    session_date: date
    slot: str = Field(min_length=1)
    execution_profile_id: str = Field(min_length=1)
    model_label: str = Field(min_length=1)
    shared_bundle_path: str = Field(min_length=1)
    shared_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    portfolio_snapshot_id: str = Field(min_length=1)
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    result: ReasoningRunResult = ReasoningRunResult.PREPARED
    decision_ids: list[str] = Field(default_factory=list)
    public_summary: str = ""

    @model_validator(mode="after")
    def require_consistent_result(self) -> "ReasoningRun":
        if len(self.decision_ids) != len(set(self.decision_ids)):
            raise ValueError("decision_ids must be unique")
        if self.result == ReasoningRunResult.PREPARED:
            if self.completed_at is not None or self.decision_ids or self.public_summary:
                raise ValueError("PREPARED runs cannot contain completion data")
            return self
        if self.completed_at is None or not self.public_summary.strip():
            raise ValueError("completed runs require completed_at and public_summary")
        if self.result == ReasoningRunResult.NO_ACTION and self.decision_ids:
            raise ValueError("NO_ACTION runs cannot contain decision_ids")
        if self.result == ReasoningRunResult.DECISIONS_AUTHORED and not self.decision_ids:
            raise ValueError("DECISIONS_AUTHORED runs require decision_ids")
        return self


def reasoning_run_id(session_date: date, slot: str, execution_profile_id: str) -> str:
    run_id = f"rr_{session_date}_{slot}_{execution_profile_id}"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        raise ValueError("reasoning run identifiers contain unsupported characters")
    return run_id
