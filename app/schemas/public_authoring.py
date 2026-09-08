"""Opt-in public prose and explicit source eligibility, separate from private research."""

import ipaddress
from datetime import date
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Reference = Annotated[str, Field(min_length=1, max_length=200)]


class PublicAuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicClaimDraft(PublicAuthoringModel):
    claim_id: Reference
    text: Text
    evidence_confidence: float | None = Field(default=None, ge=0, le=1)
    source_refs: list[Reference] = Field(default_factory=list, max_length=20)
    approved_for_publication: bool = False


class PublicStage(PublicAuthoringModel):
    stage: Literal[
        "initial_thesis",
        "counter_thesis",
        "adversarial_refinement",
        "refined_thesis",
        "what_is_priced_in",
    ]
    summary: Text
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    claim_ids: list[Reference] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def stage_times(self) -> "PublicStage":
        if self.completed_at and (self.started_at is None or self.completed_at < self.started_at):
            raise ValueError("completed stage requires an earlier start")
        return self


class PublicVariantPerception(PublicAuthoringModel):
    consensus: Text | None = None
    disagreement: Text | None = None
    evidence: Text | None = None
    falsification: Text | None = None
    claim_ids: list[Reference] = Field(default_factory=list, max_length=30)


class PublicConditions(PublicAuthoringModel):
    add: list[Text] = Field(default_factory=list, max_length=20)
    trim: list[Text] = Field(default_factory=list, max_length=20)
    exit: list[Text] = Field(default_factory=list, max_length=20)
    invalidation: list[Text] = Field(default_factory=list, max_length=20)


class PublicNarrative(PublicAuthoringModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    approved_for_publication: bool = False
    required_source_refs: list[Reference] = Field(default_factory=list, max_length=30)
    stages: list[PublicStage] = Field(default_factory=list, max_length=5)
    claims: list[PublicClaimDraft] = Field(default_factory=list, max_length=50)
    variant_perception: PublicVariantPerception | None = None
    trigger_summary: Text | None = None
    x_summary: Text | None = None
    conviction_rationale: Text | None = None
    extraordinary_opportunity_summary: Text | None = None
    conditions: PublicConditions | None = None

    @model_validator(mode="after")
    def coherent_references(self) -> "PublicNarrative":
        identifiers = [claim.claim_id for claim in self.claims]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate public claim ID")
        stages = [stage.stage for stage in self.stages]
        if len(set(stages)) != len(stages):
            raise ValueError("duplicate public stage")
        refs = [ref for stage in self.stages for ref in stage.claim_ids]
        if self.variant_perception:
            refs += self.variant_perception.claim_ids
        if not set(refs) <= set(identifiers):
            raise ValueError("unknown public claim reference")
        return self


class PublicSourceRecord(PublicAuthoringModel):
    revision_id: Reference
    source_ref: Reference
    supersedes: Reference | None = None
    recorded_at: AwareDatetime
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=200)
    published_on: date | None = None
    source_type: Literal["SEC", "COMPANY_IR", "NEWS", "X", "PRICE_DATA", "MACRO", "ETF_ISSUER"]
    url: str | None = Field(default=None, max_length=2000)
    access: Literal["public", "authenticated", "private"] = "private"
    approved_for_publication: bool = False
    excerpt: Text | None = None
    excerpt_approved: bool = False

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("public source URL must be unauthenticated HTTP(S)")
        if not host or "." not in host or host.endswith((".local", ".localhost", ".internal")):
            raise ValueError("public source URL requires a public host")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("public source URL cannot use a private address")
        if any(
            token in key.lower()
            for key, _ in parse_qsl(parsed.query)
            for token in ("token", "secret", "password", "credential", "signature", "api_key")
        ):
            raise ValueError("public source URL cannot contain credentials")
        if any(ord(char) < 32 for char in value):
            raise ValueError("public source URL cannot contain controls")
        return value

    @model_validator(mode="after")
    def explicit_eligibility(self) -> "PublicSourceRecord":
        if self.approved_for_publication and self.access != "public":
            raise ValueError("only public access sources may be approved")
        if self.supersedes == self.revision_id:
            raise ValueError("source revision cannot supersede itself")
        return self


class ThesisReview(PublicAuthoringModel):
    review_id: Reference
    mode: Literal["live", "paper"]
    account_id: Reference
    episode_id: Reference
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,11}$")
    reviewed_at: AwareDatetime
    recorded_at: AwareDatetime
    author: Literal["agent", "operator"]
    reasoning_run_id: Reference | None = None
    runtime_attempt_id: Reference | None = None
    state: Literal["not_reviewed", "intact", "under_review", "invalidated"]
    summary: Text | None = None
    narrative: PublicNarrative | None = None
    approved_for_publication: bool = False
    private_notes: Text | None = None

    @model_validator(mode="after")
    def review_identity(self) -> "ThesisReview":
        if self.recorded_at < self.reviewed_at:
            raise ValueError("review cannot be recorded before it happened")
        if (
            self.author == "agent"
            and self.reasoning_run_id is None
            and self.runtime_attempt_id is None
        ):
            raise ValueError("agent review requires a recorded run")
        return self
