"""Runtime facts and authoring output. Execution permission stays in trusted code."""

from datetime import date, time
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.decision_record import Decision, InvestmentDecisionRecord
from app.schemas.public_authoring import PublicNarrative


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeRun(RuntimeModel):
    run_id: str = Field(min_length=1, max_length=200)
    mode: Literal["live", "paper"]
    account_id: str = Field(min_length=1, max_length=200)
    execution_profile_id: str = ""
    session_date: date
    slot: str = Field(min_length=1, max_length=100)
    prepared_at: AwareDatetime
    intake_path: str = Field(min_length=1)
    intake_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reasoning_run_id: str | None = None
    occurrence_id: str | None = None
    origin: Literal["manual", "scheduled", "event"] = "manual"
    trigger_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def scope(self) -> "RuntimeRun":
        if self.origin == "event" and not self.trigger_ids:
            raise ValueError("event runs require explicit trigger references")
        if self.origin == "manual" and self.trigger_ids:
            raise ValueError("manual runs cannot claim event triggers")
        if (self.origin == "scheduled") != bool(self.occurrence_id):
            raise ValueError(
                "scheduled origin requires an occurrence and other origins cannot reserve one"
            )
        if len(set(self.trigger_ids)) != len(self.trigger_ids):
            raise ValueError("duplicate trigger reference")
        if any(not item or len(item) > 200 for item in self.trigger_ids):
            raise ValueError("invalid trigger reference")
        if self.mode == "live" and (not self.execution_profile_id or not self.reasoning_run_id):
            raise ValueError("live runtime requires profile and prepared reasoning run")
        if self.mode == "paper" and (
            self.account_id != "paper" or self.execution_profile_id or self.reasoning_run_id
        ):
            raise ValueError("paper runtime requires the paper account without a live profile")
        return self


class ScheduleRevision(RuntimeModel):
    schedule_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, le=2**63 - 1)
    mode: Literal["live", "paper"]
    account_id: str = Field(min_length=1, max_length=200)
    execution_profile_id: str = ""
    configured_at: AwareDatetime
    enabled: bool = False
    paused: bool = False
    schedule_mode: Literal["manual", "scheduled"] = "manual"
    timezone: Literal["America/New_York"] = "America/New_York"
    slot: str = Field(default="close", min_length=1, max_length=100)
    due_local: time = time(17, 45)
    early_close_due_local: time | None = time(14, 45)
    grace_seconds: int = Field(default=1800, ge=0, le=86400)
    observer_max_age_seconds: int = Field(default=180, ge=10, le=3600)
    task_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def local_times(self) -> "ScheduleRevision":
        if self.due_local.tzinfo or (
            self.early_close_due_local and self.early_close_due_local.tzinfo
        ):
            raise ValueError("schedule times are local wall-clock times without an offset")
        if self.mode == "live" and not self.execution_profile_id:
            raise ValueError("live schedule requires profile")
        if self.mode == "paper" and (self.account_id != "paper" or self.execution_profile_id):
            raise ValueError("paper schedule requires the paper account")
        return self


class SchedulerObservation(RuntimeModel):
    schedule_id: str
    revision: int = Field(ge=1)
    observed_at: AwareDatetime
    observer: Literal["worker", "windows_task"]
    configured: bool
    enabled: bool
    next_run_at: AwareDatetime | None = None


class AuthoredThesisReview(RuntimeModel):
    episode_id: str = Field(min_length=1, max_length=200)
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    state: Literal["not_reviewed", "intact", "under_review", "invalidated"]
    summary: str | None = Field(default=None, max_length=4000)
    narrative: PublicNarrative | None = None
    approved_for_publication: bool = False
    private_notes: str | None = Field(default=None, max_length=4000)


class CandidateConsidered(RuntimeModel):
    """One researched idea and where it ended up: the review's hunt ledger."""

    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    idea_source: str = Field(min_length=1, max_length=300)
    sources_opened: list[str] = Field(default_factory=list, max_length=12)
    outcome: Decision
    reason: str = Field(min_length=1, max_length=2000)


class AuthoredOutput(RuntimeModel):
    decisions: list[InvestmentDecisionRecord] = Field(default_factory=list, max_length=20)
    thesis_reviews: list[AuthoredThesisReview] = Field(default_factory=list, max_length=20)
    candidates_considered: list[CandidateConsidered] = Field(default_factory=list, max_length=12)
    public_summary: str = Field(min_length=1, max_length=4000)


class RuntimeAttempt(RuntimeModel):
    attempt_id: str
    public_id: str
    run_id: str
    attempt_number: int
    fence: int
    status: Literal[
        "running", "completed", "no_action", "failed", "blocked", "timed_out", "canceled", "expired"
    ]
    stage: Literal["starting", "authoring", "validating", "submitting", "finished"]
    model: str
    observed_model: str | None = None
    started_at: AwareDatetime
    heartbeat_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    reason: str | None = None
    public_summary: str | None = None
