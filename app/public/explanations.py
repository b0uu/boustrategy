"""Public projections of explicitly approved narrative and recorded evaluation facts."""

import hashlib
import sqlite3
from decimal import Decimal
from typing import Any

from app.dashboard.queries import table_exists
from app.schemas.policy_reporting import PolicyEvaluationRecord
from app.schemas.public_authoring import PublicNarrative, PublicSourceRecord, ThesisReview
from app.schemas.reporting import FillObservation
from app.x.calendar import NEW_YORK


def eligible_sources(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if not table_exists(conn, "public_source_records"):
        return {}
    sources = {}
    for public_id, raw in conn.execute(
        "SELECT s.public_id, s.record_json FROM public_source_records s WHERE NOT EXISTS "
        "(SELECT 1 FROM public_source_records n WHERE n.supersedes=s.revision_id)"
    ):
        source = PublicSourceRecord.model_validate_json(raw)
        if source.approved_for_publication and source.access == "public":
            sources[source.source_ref] = {
                "public_id": public_id,
                "title": source.title,
                "publisher": source.publisher,
                "published_on": source.published_on.isoformat() if source.published_on else None,
                "source_type": source.source_type,
                "url": source.url,
                # X post content is never republished; only its public metadata is exposed.
                "excerpt": source.excerpt
                if source.excerpt_approved and source.source_type != "X"
                else None,
            }
    return sources


def narrative_projection(
    narrative: PublicNarrative | None, sources: dict[str, dict[str, Any]], public_id: str
) -> dict[str, Any] | None:
    if narrative is None or not narrative.approved_for_publication:
        return None
    if not set(narrative.required_source_refs) <= sources.keys():
        return None
    claims = [
        c
        for c in narrative.claims
        if c.approved_for_publication and set(c.source_refs) <= sources.keys()
    ]
    claim_ids = {
        c.claim_id: "claim_" + hashlib.sha256(f"{public_id}/{c.claim_id}".encode()).hexdigest()[:24]
        for c in claims
    }
    stages = [
        {
            "stage": stage.stage,
            "summary": stage.summary,
            "started_at": stage.started_at.isoformat() if stage.started_at else None,
            "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
            "claim_ids": [claim_ids[ref] for ref in stage.claim_ids],
        }
        for stage in narrative.stages
        if set(stage.claim_ids) <= claim_ids.keys()
    ]
    variant = None
    if (
        narrative.variant_perception
        and set(narrative.variant_perception.claim_ids) <= claim_ids.keys()
    ):
        variant = narrative.variant_perception.model_dump(mode="json")
        variant["claim_ids"] = [claim_ids[ref] for ref in narrative.variant_perception.claim_ids]
    used_sources = set(narrative.required_source_refs)
    used_sources.update(ref for claim in claims for ref in claim.source_refs)
    return {
        "company_name": narrative.company_name,
        "stages": stages,
        "claims": [
            {
                "public_id": claim_ids[c.claim_id],
                "claim": c.text,
                "evidence_confidence": c.evidence_confidence,
                "confidence_method": "model_assessed_evidence"
                if c.evidence_confidence is not None
                else None,
                "source_ids": [sources[ref]["public_id"] for ref in c.source_refs],
            }
            for c in claims
        ],
        "sources": [sources[ref] for ref in sorted(used_sources)],
        "variant_perception": variant,
        "trigger_summary": narrative.trigger_summary,
        "x_summary": narrative.x_summary,
        "conviction_rationale": narrative.conviction_rationale,
        "extraordinary_opportunity_summary": narrative.extraordinary_opportunity_summary,
        "conditions": narrative.conditions.model_dump(mode="json")
        if narrative.conditions
        else None,
    }


def policy_projection(record: PolicyEvaluationRecord | None) -> dict[str, Any]:
    if record is None:
        return {
            "status": "unavailable",
            "reason": "historical_evaluation_not_recorded",
            "policy_version": None,
            "validator_version": None,
            "checks": [],
        }
    regime = None
    if record.regime_snapshot:
        snapshot = record.regime_snapshot
        units = {
            "spy_trend": "fraction",
            "qqq_trend": "fraction",
            "spy_trend_slope": "fraction",
            "qqq_trend_slope": "fraction",
            "drawdown": "fraction",
            "spy_volatility": "percentile",
        }
        components = []
        for name, unit in units.items():
            component = snapshot.components.get(name)
            if (
                isinstance(component, dict)
                and isinstance(component.get("value"), int | float)
                and isinstance(component.get("points"), int)
            ):
                components.append(
                    {
                        "name": name,
                        "value": component["value"],
                        "points": component["points"],
                        "unit": unit,
                    }
                )
        regime = {
            "raw_state": snapshot.raw_state,
            "published_state": snapshot.state,
            "score": snapshot.score,
            "as_of": snapshot.computed_at.isoformat(),
            "components": components,
        }
    return {
        "status": "available",
        "regime_evidence": regime,
        "evaluated_at": record.evaluated_at.isoformat(),
        "policy_version": record.policy_version,
        "validator_version": record.validator_version,
        "validator_schema_sha256": record.validator_schema_sha256,
        "authored_schema_version": record.authored_schema_version,
        "approved": record.approved,
        "checks": [
            {
                **check.model_dump(mode="json"),
                "name": check.name or "Historical rule label unavailable",
                "explanation": check.failure_explanation if check.result == "failed" else None,
            }
            for check in record.checks
        ],
        "input_provenance": {
            "portfolio": "bound_snapshot"
            if record.portfolio_snapshot
            else "recorded_context"
            if record.portfolio
            else "unavailable",
            "regime": "bound_snapshot"
            if record.regime_snapshot
            else "recorded_state"
            if record.true_regime_state
            else "unavailable",
            "regime_as_of": record.regime_snapshot.computed_at.isoformat()
            if record.regime_snapshot
            else None,
        },
    }


def execution_projection(fills: list[FillObservation]) -> dict[str, Any]:
    if not fills:
        return {
            "status": "unavailable",
            "reason": "confirmed_execution_not_recorded",
            "quantity": None,
            "gross_notional": None,
            "fees": None,
            "items": [],
        }
    ordered = sorted(fills, key=lambda fill: (fill.occurred_at, fill.sequence))
    return {
        "status": "recorded",
        "quantity": str(sum((f.quantity for f in fills), Decimal(0))),
        "gross_notional": str(sum((f.gross_notional for f in fills), Decimal(0))),
        "fees": str(sum((f.fee for f in fills if f.fee is not None), Decimal(0)))
        if all(f.fee is not None for f in fills)
        else None,
        "slippage": None,
        "slippage_reason": "reference_price_not_recorded",
        "total": len(fills),
        "truncated": len(fills) > 100,
        "items": [
            {
                "occurred_at": f.occurred_at.isoformat(),
                "side": f.side,
                "quantity": str(f.quantity),
                "price": str(f.price),
                "gross_notional": str(f.gross_notional),
                "fee": str(f.fee) if f.fee is not None else None,
                "order_state": f.order_state,
                "canceled_quantity": str(f.canceled_quantity),
                "settled_at": f.settled_at.isoformat() if f.settled_at else None,
            }
            for f in ordered[-100:]
        ],
    }


def thesis_projection(
    review: ThesisReview | None, sources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if review is None or not review.approved_for_publication:
        return {
            "state": "not_reviewed",
            "reviewed_at": None,
            "summary": None,
            "reason": "public_review_unavailable",
        }
    review_sources = {
        ref: metadata
        for ref, metadata in sources.items()
        if metadata["published_on"] is None
        or metadata["published_on"] <= review.reviewed_at.astimezone(NEW_YORK).date().isoformat()
    }
    narrative = narrative_projection(review.narrative, review_sources, review.episode_id)
    if review.narrative and review.narrative.required_source_refs and narrative is None:
        return {
            "state": "not_reviewed",
            "reviewed_at": None,
            "summary": None,
            "reason": "required_evidence_unavailable",
        }
    return {
        "state": review.state,
        "reviewed_at": review.reviewed_at.isoformat(),
        "summary": review.summary,
        "narrative": narrative,
        "author": review.author,
        "run_provenance": "recorded"
        if review.reasoning_run_id or review.runtime_attempt_id
        else "operator_review",
    }
