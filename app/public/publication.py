"""Trusted publication into a separate, explicitly public read model.

Run this after ingestion, never from a public request. Profile IDs are supplied
by the operator; model labels aren't account identity.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.dashboard.queries import table_exists
from app.paper.broker import cash_balance
from app.performance.paper import paper_observations
from app.performance.report import holding_episodes, materialize
from app.performance.storage import current_observations
from app.policy.catalog import catalog
from app.public import activity, explanations
from app.public.database import open_readonly
from app.schemas.broker_execution import BrokerExecutionRecord, BrokerExecutionStatus
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.live_execution import LiveExecutionPacket
from app.schemas.policy_reporting import PolicyEvaluationRecord
from app.schemas.public_authoring import ThesisReview
from app.schemas.reporting import (
    CoverageObservation,
    FillObservation,
    ReportingObservation,
    ValuationObservation,
)
from app.x.calendar import NEW_YORK, CalendarCoverageError, completed_session

_PUBLIC_LIFECYCLE = {
    "decision_recorded",
    "schema_validated",
    "schema_failed",
    "policy_approved",
    "policy_rejected",
    "order_intent_created",
    "paper_filled",
}
_PUBLIC_SOURCE_TYPES = {"SEC", "COMPANY_IR", "NEWS", "X", "PRICE_DATA", "MACRO", "ETF_ISSUER"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    revision INTEGER NOT NULL, updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO publication_meta VALUES (1, 0, '');
CREATE TABLE IF NOT EXISTS public_decisions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    public_id TEXT NOT NULL UNIQUE,
    portfolio_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    policy TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    withdrawn INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS public_feed ON public_decisions
    (portfolio_id, revoked, withdrawn, created_at DESC, public_id DESC);
CREATE INDEX IF NOT EXISTS public_ticker ON public_decisions
    (portfolio_id, ticker, created_at DESC, public_id DESC);
CREATE INDEX IF NOT EXISTS public_run ON public_decisions
    (portfolio_id, json_extract(content, '$.public_run_id'), created_at DESC, public_id DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS public_search USING fts5(ticker, summary, theme);
DROP TRIGGER IF EXISTS public_search_insert;
CREATE TRIGGER public_search_insert AFTER INSERT ON public_decisions BEGIN
    INSERT INTO public_search(rowid, ticker, summary, theme)
    VALUES(new.sequence, new.ticker,
    CASE WHEN new.revoked OR new.withdrawn THEN ''
    ELSE new.summary || ' ' || COALESCE(json_extract(new.content, '$.company_name'), '') END,
    CASE WHEN new.revoked OR new.withdrawn THEN '' ELSE json_extract(new.content, '$.theme') END);
END;
DROP TRIGGER IF EXISTS public_search_update;
CREATE TRIGGER public_search_update AFTER UPDATE ON public_decisions BEGIN
    DELETE FROM public_search WHERE rowid=old.sequence;
    INSERT INTO public_search(rowid, ticker, summary, theme)
    VALUES(new.sequence, new.ticker,
    CASE WHEN new.revoked OR new.withdrawn THEN ''
    ELSE new.summary || ' ' || COALESCE(json_extract(new.content, '$.company_name'), '') END,
    CASE WHEN new.revoked OR new.withdrawn THEN '' ELSE json_extract(new.content, '$.theme') END);
END;
CREATE TABLE IF NOT EXISTS public_performance (
    portfolio_id TEXT NOT NULL, range_name TEXT NOT NULL, content TEXT NOT NULL,
    PRIMARY KEY(portfolio_id, range_name)
);
CREATE TABLE IF NOT EXISTS public_rule_triggers (
    rule_id TEXT NOT NULL, public_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL, PRIMARY KEY(rule_id, public_id)
);
CREATE INDEX IF NOT EXISTS rule_trigger_lookup ON public_rule_triggers
    (portfolio_id, rule_id, evaluated_at DESC, public_id DESC);
CREATE TABLE IF NOT EXISTS public_portfolios (
    portfolio_id TEXT PRIMARY KEY, content TEXT NOT NULL
);
"""


def initialize(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executescript(activity._SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(public_decisions)")}
    if "feed_content" not in columns:
        conn.execute(
            "ALTER TABLE public_decisions ADD COLUMN feed_content TEXT NOT NULL DEFAULT '{}'"
        )
        conn.execute("UPDATE public_decisions SET feed_content=content")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public_policy "
        "(portfolio_id TEXT PRIMARY KEY, content TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def revoke(path: str | Path, public_id: str) -> bool:
    conn = initialize(path)
    try:
        with conn:
            changed = conn.execute(
                "UPDATE public_decisions SET revoked = 1 WHERE public_id = ? AND revoked = 0",
                (public_id,),
            ).rowcount
            if changed:
                portfolio_row = conn.execute(
                    "SELECT portfolio_id FROM public_decisions WHERE public_id=?", (public_id,)
                ).fetchone()
                if portfolio_row:
                    scope = portfolio_row[0]
                    counts = {"approved": 0, "rejected": 0, "unavailable": 0}
                    for policy, count in conn.execute(
                        "SELECT policy, COUNT(*) FROM public_decisions WHERE portfolio_id=? "
                        "AND revoked=0 AND withdrawn=0 GROUP BY policy",
                        (scope,),
                    ):
                        counts[policy] = count
                    today_start = datetime.now(NEW_YORK).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    today = today_start.date().isoformat()
                    today_count = conn.execute(
                        "SELECT COUNT(*) FROM public_decisions WHERE portfolio_id=? AND "
                        "revoked=0 AND withdrawn=0 AND created_at>=? AND created_at<?",
                        (
                            scope,
                            today_start.astimezone(UTC).isoformat(),
                            (today_start + timedelta(days=1)).astimezone(UTC).isoformat(),
                        ),
                    ).fetchone()[0]
                    conn.execute(
                        "UPDATE public_portfolios SET content=json_set(content, "
                        "'$.decision_counts', json(?), '$.decision_count_date', ?, "
                        "'$.decisions_today', ?) WHERE portfolio_id=?",
                        (json.dumps(counts, sort_keys=True), today, today_count, scope),
                    )
                conn.execute(
                    "UPDATE publication_meta SET revision = revision + 1, updated_at = ?",
                    (datetime.now(UTC).isoformat(),),
                )
            return bool(changed)
    finally:
        conn.close()


def publish(
    source_path: str | Path,
    public_path: str | Path,
    *,
    live_profiles: tuple[str, ...] = (),
    live_account_id: str | None = None,
    rebuild: bool = False,
) -> dict[str, int]:
    if Path(source_path).resolve() == Path(public_path).resolve():
        raise ValueError("public store must be separate from source")
    if not Path(source_path).is_file():
        raise FileNotFoundError("source database does not exist")
    target = initialize(public_path)
    counts = {"inserted": 0, "updated": 0, "withdrawn": 0}
    try:
        with open_readonly(source_path, allow_wal=True) as source, target:
            published_at = datetime.now(UTC)
            now = published_at.isoformat()
            changes = (
                source.execute(
                    "SELECT source_id, details, performance, activity FROM "
                    "publication_changes WHERE singleton=1"
                ).fetchone()
                if table_exists(source, "publication_changes")
                else None
            )
            try:
                eligible_close = completed_session(published_at).isoformat()
            except CalendarCoverageError:
                eligible_close = "calendar_out_of_coverage"
            accounting_clock = [
                published_at.astimezone(NEW_YORK).date().isoformat(),
                eligible_close,
            ]
            # The public file needs identity equality, not profile IDs or account fingerprints.
            identity = hashlib.sha256(
                json.dumps(
                    {"profiles": sorted(live_profiles), "account": live_account_id},
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            checkpoint = json.dumps(
                {
                    "version": 9,
                    "accounting_clock": accounting_clock,
                    "identity": identity,
                    "changes": changes,
                },
                sort_keys=True,
            )
            previous_row = target.execute(
                "SELECT content FROM publication_checkpoint WHERE singleton=1"
            ).fetchone()
            previous = json.loads(previous_row[0]) if previous_row and not rebuild else None
            current = json.loads(checkpoint)
            if changes and previous == current:
                return counts
            same_configuration = bool(
                changes
                and previous
                and previous["version"] == current["version"]
                and previous["identity"] == current["identity"]
                and previous["changes"]
                and previous["changes"][0] == current["changes"][0]
                and all(
                    old <= new
                    for old, new in zip(
                        previous["changes"][1:], current["changes"][1:], strict=True
                    )
                )
            )
            activity.publish_activity(
                source,
                target,
                live_profiles,
                published_at,
                since=previous["changes"][3] if same_configuration and previous else None,
            )
            target.execute(
                "INSERT INTO publication_checkpoint VALUES (1, ?) ON "
                "CONFLICT(singleton) DO UPDATE SET content=excluded.content",
                (checkpoint,),
            )
            if (
                changes
                and previous
                and previous["version"] == current["version"]
                and previous["identity"] == current["identity"]
                and previous["changes"]
                and previous["changes"][:3] == current["changes"][:3]
                and previous.get("accounting_clock") == accounting_clock
            ):
                target.execute("UPDATE publication_meta SET updated_at=?", (now,))
                return counts
            partial_details = bool(
                same_configuration
                and previous
                and table_exists(source, "publication_rebuild")
                and source.execute(
                    "SELECT details_revision FROM publication_rebuild WHERE singleton=1"
                ).fetchone()[0]
                <= previous["changes"][1]
            )
            selection = (
                (
                    " WHERE decision_id IN (SELECT decision_id FROM "
                    "publication_decision_changes WHERE revision>"
                    + str(previous["changes"][1])
                    + ")"
                )
                if partial_details and previous
                else ""
            )
            selected_ids = "SELECT decision_id FROM decision_records" + selection
            selected_intents = (
                "SELECT order_intent_id FROM order_intents WHERE decision_id IN ("
                + selected_ids
                + ")"
            )
            performance_changed = (
                not same_configuration
                or not previous
                or previous["changes"][2] != current["changes"][2]
                or previous.get("accounting_clock") != accounting_clock
            )
            source_rows = (
                source.execute(
                    "SELECT decision_id, record_json FROM decision_records" + selection
                ).fetchall()
                if table_exists(source, "decision_records")
                else []
            )
            intents = (
                {
                    row[0]: (row[1], row[2], row[3])
                    for row in source.execute(
                        "SELECT decision_id, execution_mode, execution_profile_id, "
                        "order_intent_id FROM order_intents" + selection
                    )
                }
                if table_exists(source, "order_intents")
                else {}
            )
            runs = (
                {
                    row[0]: row[1]
                    for row in source.execute(
                        "SELECT d.decision_id, r.execution_profile_id FROM "
                        "reasoning_run_decisions d JOIN reasoning_runs r "
                        "USING(reasoning_run_id) WHERE d.decision_id IN (" + selected_ids + ")"
                    )
                }
                if table_exists(source, "reasoning_run_decisions")
                and table_exists(source, "reasoning_runs")
                else {}
            )
            statuses: dict[str, list[str]] = {}
            if table_exists(source, "status_events"):
                for subject, status in source.execute(
                    "SELECT subject_id, status FROM status_events "
                    "WHERE subject_type='decision' AND subject_id IN ("
                    + selected_ids
                    + ") ORDER BY event_id"
                ):
                    statuses.setdefault(subject, []).append(status)
            filled = (
                {
                    row[0]
                    for row in source.execute(
                        "SELECT order_intent_id FROM paper_fills WHERE order_intent_id IN ("
                        + selected_intents
                        + ")"
                    )
                }
                if table_exists(source, "paper_fills")
                else set()
            )
            sized_orders: dict[str, dict[str, Any]] = {}
            if table_exists(source, "live_execution_packets"):
                for intent_id, raw_packet in source.execute(
                    "SELECT order_intent_id, packet_json FROM live_execution_packets "
                    "WHERE order_intent_id IN (" + selected_intents + ") ORDER BY created_at"
                ):
                    packet = LiveExecutionPacket.model_validate_json(raw_packet)
                    sized_orders[intent_id] = {
                        "notional": packet.notional,
                        "limit_price": packet.limit_price,
                        "side": packet.side.value,
                        "order_type": packet.order_type.value,
                        "sized_at": packet.created_at.isoformat(),
                        "expires_at": packet.expires_at.isoformat(),
                        "status": "prepared_execution_packet",
                    }
            requested: dict[str, dict[str, Any]] = {}
            if table_exists(source, "broker_execution_records"):
                for intent_id, execution_json in source.execute(
                    "SELECT order_intent_id, record_json FROM broker_execution_records "
                    "WHERE order_intent_id IN (" + selected_intents + ")"
                ):
                    execution_record = BrokerExecutionRecord.model_validate_json(execution_json)
                    requested[intent_id] = {
                        "notional": execution_record.requested_notional,
                        "limit_price": execution_record.limit_price,
                        "order_type": execution_record.order_type.value,
                        "broker_status": execution_record.status.value.lower(),
                        "submitted_at": execution_record.submitted_at.isoformat(),
                    }
            broker_milestones: dict[str, list[dict[str, str]]] = {}
            if table_exists(source, "broker_execution_events"):
                for intent_id, status, at in source.execute(
                    "SELECT order_intent_id, status, occurred_at FROM broker_execution_events "
                    "WHERE order_intent_id IN ("
                    + selected_intents
                    + ") ORDER BY occurred_at, broker_event_id"
                ):
                    if status in {item.value for item in BrokerExecutionStatus}:
                        broker_milestones.setdefault(intent_id, []).append(
                            {"stage": "broker_" + status.lower(), "occurred_at": at}
                        )
            for broker_events in broker_milestones.values():
                broker_events.sort(key=lambda event: datetime.fromisoformat(event["occurred_at"]))
            sources = explanations.eligible_sources(source)
            registered_refs = (
                {
                    row[0]
                    for row in source.execute(
                        "SELECT DISTINCT source_ref FROM public_source_records"
                    )
                }
                if table_exists(source, "public_source_records")
                else set()
            )
            evaluations = (
                {
                    row[0]: PolicyEvaluationRecord.model_validate_json(row[1])
                    for row in source.execute(
                        "SELECT decision_id, evaluation_json FROM policy_evaluations" + selection
                    )
                }
                if table_exists(source, "policy_evaluations")
                else {}
            )
            run_metadata = (
                dict(
                    source.execute(
                        "SELECT d.decision_id, r.model_label FROM reasoning_run_decisions d "
                        "JOIN reasoning_runs r USING(reasoning_run_id) WHERE d.decision_id IN ("
                        + selected_ids
                        + ")"
                    )
                )
                if table_exists(source, "reasoning_run_decisions")
                else {}
            )
            runtime_provenance = {}
            public_runs = {}
            run_ids: dict[str, str | None] = {}
            if table_exists(source, "runtime_attempts"):
                for decision_id, run_id, attempt_id, model, observed in source.execute(
                    "SELECT d.decision_id, r.run_id, a.public_id, a.model, "
                    "a.observed_model FROM decision_records d JOIN runtime_attempts a "
                    "ON a.attempt_id=d.runtime_attempt_id JOIN runtime_runs r ON "
                    "r.run_id=a.run_id WHERE d.decision_id IN (" + selected_ids + ")"
                ):
                    if run_id not in run_ids:
                        mapped = target.execute(
                            "SELECT public_id FROM public_run_ids WHERE source_key=?",
                            (hashlib.sha256(run_id.encode()).hexdigest(),),
                        ).fetchone()
                        run_ids[run_id] = mapped[0] if mapped else None
                    runtime_provenance[decision_id] = {
                        "public_run_id": run_ids[run_id],
                        "public_attempt_id": attempt_id,
                        "requested_model": model,
                        "observed_model": observed,
                    }
            if table_exists(source, "reasoning_run_decisions"):
                for decision_id, legacy_id in source.execute(
                    "SELECT decision_id, reasoning_run_id FROM reasoning_run_decisions" + selection
                ):
                    if legacy_id not in run_ids:
                        mapped = target.execute(
                            "SELECT public_id FROM public_run_ids WHERE source_key=?",
                            (hashlib.sha256(legacy_id.encode()).hexdigest(),),
                        ).fetchone()
                        run_ids[legacy_id] = mapped[0] if mapped else None
                    if run_ids[legacy_id]:
                        public_runs[decision_id] = run_ids[legacy_id]
            milestones: dict[str, list[dict[str, str]]] = {}
            if table_exists(source, "status_events"):
                for subject, status, at in source.execute(
                    "SELECT subject_id, status, occurred_at FROM status_events "
                    "WHERE subject_type='decision' AND subject_id IN ("
                    + selected_ids
                    + ") ORDER BY event_id"
                ):
                    if status in _PUBLIC_LIFECYCLE or status in {
                        "decision_record_created",
                        "schema_validated",
                        "schema_failed",
                        "policy_approved",
                        "policy_rejected",
                        "order_intent_created",
                    }:
                        milestones.setdefault(subject, []).append(
                            {
                                "stage": status,
                                "occurred_at": at,
                                "time_precision": "timestamp"
                                if datetime.fromisoformat(at).tzinfo
                                else "date_or_local_time",
                            }
                        )
            reviews: dict[tuple[str, str, str], ThesisReview] = {}
            if table_exists(source, "thesis_reviews"):
                for (review_json,) in source.execute("SELECT record_json FROM thesis_reviews"):
                    review = ThesisReview.model_validate_json(review_json)
                    review_key = (review.mode, review.account_id, review.episode_id)
                    if (
                        review_key not in reviews
                        or reviews[review_key].reviewed_at < review.reviewed_at
                    ):
                        reviews[review_key] = review
            fingerprints: set[str] = set()
            latest_live = None
            if table_exists(source, "live_portfolio_snapshots"):
                for profile, raw in source.execute(
                    "SELECT execution_profile_id, snapshot_json FROM live_portfolio_snapshots "
                    "ORDER BY captured_at DESC"
                ):
                    if profile in live_profiles:
                        snapshot = json.loads(raw)
                        fingerprints.add(snapshot["broker_account_fingerprint"])
                        if latest_live is None:
                            latest_live = snapshot
            if len(fingerprints) > 1:
                raise ValueError("live profiles map to multiple accounts")
            if live_account_id and fingerprints and fingerprints != {live_account_id}:
                raise ValueError("explicit live account does not match profile snapshots")
            reporting_account = live_account_id or next(iter(fingerprints), None)
            reporting_by_scope: dict[str, list[ReportingObservation]] = {}
            company_names: dict[tuple[str, str], str] = {}
            for mode, account in (("live", reporting_account), ("paper", "paper")):
                reporting_by_scope[mode] = (
                    current_observations(source, mode=mode, account_id=account)
                    if account and table_exists(source, "reporting_observations")
                    else []
                )
                for observation in reporting_by_scope[mode]:
                    if isinstance(observation, ValuationObservation):
                        for position in observation.positions or []:
                            if position.name:
                                company_names[(mode, position.ticker)] = position.name
            if not reporting_by_scope["paper"]:
                reconstructed, paper_issue = paper_observations(source, observed_at=published_at)
                if not paper_issue:
                    reporting_by_scope["paper"] = reconstructed
            fills_by_decision: dict[tuple[str, str], list[FillObservation]] = {}
            for mode, observations in reporting_by_scope.items():
                for observation in observations:
                    if isinstance(observation, FillObservation) and observation.decision_id:
                        fills_by_decision.setdefault((mode, observation.decision_id), []).append(
                            observation
                        )
            seen: set[str] = set()
            for decision_id, raw_json in source_rows:
                record = InvestmentDecisionRecord.model_validate_json(raw_json)
                raw = record.model_dump(mode="json")
                decision_sources = {
                    ref: metadata
                    for ref, metadata in sources.items()
                    if metadata["published_on"] is None
                    or metadata["published_on"]
                    <= record.created_at.astimezone(NEW_YORK).date().isoformat()
                }
                evaluation = evaluations.get(decision_id)
                intent = intents.get(decision_id)
                run_profile = runs.get(decision_id)
                if run_profile and intent and (intent[0] != "LIVE" or intent[1] != run_profile):
                    raise ValueError("conflicting decision scope provenance")
                ledger_profile = (
                    evaluation.execution_profile_id
                    if evaluation and evaluation.execution_mode == "LIVE"
                    else None
                )
                profile = (
                    run_profile
                    or (intent[1] if intent and intent[0] == "LIVE" else None)
                    or ledger_profile
                )
                if evaluation and (
                    profile
                    and (evaluation.execution_mode != "LIVE" or ledger_profile != profile)
                    or intent
                    and evaluation.execution_mode != intent[0]
                ):
                    raise ValueError("conflicting policy evaluation scope")
                scope = (
                    "live"
                    if profile in live_profiles
                    else "paper"
                    if not profile
                    and (
                        (intent and intent[0] == "PAPER")
                        or (evaluation and evaluation.execution_mode == "PAPER")
                    )
                    else None
                )
                if not scope or not raw.get("public_summary", "").strip():
                    continue
                if (
                    record.public_narrative
                    and record.public_narrative.approved_for_publication
                    and not set(record.public_narrative.required_source_refs)
                    <= decision_sources.keys()
                ):
                    continue
                key = hashlib.sha256(decision_id.encode()).hexdigest()
                seen.add(key)
                existing = target.execute(
                    "SELECT public_id, content, portfolio_id, withdrawn FROM public_decisions "
                    "WHERE source_key = ?",
                    (key,),
                ).fetchone()
                public_id = existing[0] if existing else f"dec_{uuid4().hex}"
                events = statuses.get(decision_id, [])
                schema = (
                    "failed"
                    if "schema_failed" in events
                    else "passed"
                    if "schema_validated" in events
                    else "unavailable"
                )
                policy = (
                    "rejected"
                    if "policy_rejected" in events
                    else "approved"
                    if "policy_approved" in events
                    else "unavailable"
                )
                lifecycle = next(
                    (status for status in reversed(events) if status in _PUBLIC_LIFECYCLE),
                    "unavailable",
                )
                if scope == "paper" and intent:
                    lifecycle = "paper_filled" if intent[2] in filled else "awaiting_paper_price"
                elif intent and broker_milestones.get(intent[2]):
                    latest_events = broker_milestones[intent[2]]
                    latest_instant = datetime.fromisoformat(latest_events[-1]["occurred_at"])
                    latest_states = {
                        event["stage"]
                        for event in latest_events
                        if datetime.fromisoformat(event["occurred_at"]) == latest_instant
                    }
                    lifecycle = (
                        next(iter(latest_states))
                        if len(latest_states) == 1
                        else "broker_status_ambiguous"
                    )
                elif intent and requested.get(intent[2]):
                    lifecycle = "broker_" + requested[intent[2]]["broker_status"]
                item = {
                    "ticker": raw["ticker"],
                    "created_at": raw["created_at"],
                    "decision": raw["decision"],
                    "public_summary": raw["public_summary"],
                    "policy_outcome": policy,
                    "schema_outcome": schema,
                    "lifecycle": lifecycle,
                    "regime": raw["regime_state"],
                    "theme": raw.get("primary_theme_id") or None,
                }
                # Dedicated public narrative and approved claims cross this boundary.
                content = {
                    **item,
                    "public_id": public_id,
                    "public_run_id": runtime_provenance.get(decision_id, {}).get("public_run_id")
                    or public_runs.get(decision_id),
                    "portfolio_id": scope,
                    "mode": scope,
                    "company_name": company_names.get((scope, str(raw["ticker"]))),
                    "proposed_target_weight": raw.get("proposed_target_weight"),
                    "final_target_weight": raw.get("final_target_weight"),
                    "claims": [
                        {
                            "claim": c["claim"],
                            "source_type": c["source_type"],
                            "source_timestamp": c["source_timestamp"],
                        }
                        for c in raw.get("source_claims", [])
                        if c.get("public_safe")
                        and c.get("source_type") in _PUBLIC_SOURCE_TYPES
                        and all(
                            ref not in registered_refs or ref in decision_sources
                            for ref in c.get("source_ids", [])
                        )
                    ],
                    "x_usage": {
                        "used": raw["x_signal_usage"]["used"],
                        "usage_type": raw["x_signal_usage"]["usage_type"],
                        "summary": "",
                        "confirmed_outside_x": raw["x_signal_usage"]["confirmed_outside_x"],
                    },
                    "narrative_status": "public_summary_only",
                }
                narrative = explanations.narrative_projection(
                    record.public_narrative, decision_sources, public_id
                )
                content.update(
                    narrative=narrative,
                    narrative_status="approved_public_stages"
                    if narrative
                    else "public_summary_only",
                    policy_evaluation=explanations.policy_projection(evaluation),
                    milestones=milestones.get(decision_id, []),
                    model_provenance={
                        "status": "recorded"
                        if decision_id in run_metadata or decision_id in runtime_provenance
                        else "unavailable",
                        "model_label": runtime_provenance.get(decision_id, {}).get(
                            "requested_model"
                        )
                        or run_metadata.get(decision_id),
                        **runtime_provenance.get(decision_id, {}),
                    },
                    current_weight=evaluation.input_identity.current_weight if evaluation else None,
                    execution=explanations.execution_projection(
                        fills_by_decision.get((scope, decision_id), [])
                    ),
                    export_version="public-decision-2",
                    requested_order=requested.get(intent[2]) if intent else None,
                    sized_order=sized_orders.get(intent[2]) if intent else None,
                    extraordinary_opportunity={
                        "invoked": record.extraordinary_opportunity,
                        "scope": [
                            "red_regime_exposure",
                            "de_risking_exposure",
                            "ordinary_buy_add_quota",
                        ],
                        "summary": narrative.get("extraordinary_opportunity_summary")
                        if narrative
                        else None,
                    },
                )
                if intent:
                    broker_record = requested.get(intent[2])
                    if broker_record:
                        content["milestones"] = [
                            *content["milestones"],
                            {
                                "stage": "broker_review_recorded"
                                if broker_record["broker_status"] == "reviewed"
                                else "broker_submission_recorded",
                                "occurred_at": broker_record["submitted_at"],
                                "time_precision": "timestamp",
                            },
                        ]
                    content["milestones"] = sorted(
                        content["milestones"] + broker_milestones.get(intent[2], []),
                        key=lambda item: (
                            datetime.fromisoformat(item["occurred_at"])
                            if datetime.fromisoformat(item["occurred_at"]).tzinfo
                            else datetime.max.replace(tzinfo=UTC)
                        ),
                    )
                content["milestones_total"] = len(content["milestones"])
                content["milestones_truncated"] = len(content["milestones"]) > 100
                if content["milestones_truncated"]:
                    content["milestones"] = content["milestones"][:6] + content["milestones"][-94:]
                if narrative and narrative["company_name"]:
                    content["company_name"] = narrative["company_name"]
                if narrative:
                    content["x_usage"]["summary"] = narrative["x_summary"] or ""
                content["created_at"] = (
                    datetime.fromisoformat(str(raw["created_at"]).replace("Z", "+00:00"))
                    .astimezone(UTC)
                    .isoformat()
                )
                compact = {
                    key: content[key]
                    for key in (
                        "ticker",
                        "created_at",
                        "decision",
                        "public_summary",
                        "policy_outcome",
                        "schema_outcome",
                        "lifecycle",
                        "regime",
                        "theme",
                        "public_id",
                        "public_run_id",
                        "portfolio_id",
                        "mode",
                        "company_name",
                    )
                }
                compact["summary_truncated"] = len(compact["public_summary"]) > 600
                compact["public_summary"] = compact["public_summary"][:600]
                feed_encoded = json.dumps(compact, sort_keys=True)
                target.execute("DELETE FROM public_rule_triggers WHERE public_id=?", (public_id,))
                if evaluation:
                    target.executemany(
                        "INSERT INTO public_rule_triggers VALUES (?, ?, ?, ?)",
                        [
                            (check.rule_id, public_id, scope, evaluation.evaluated_at.isoformat())
                            for check in evaluation.checks
                            if check.result == "failed"
                        ],
                    )
                encoded = json.dumps(content, sort_keys=True)
                if existing and encoded == existing[1] and scope == existing[2] and not existing[3]:
                    continue
                values = (
                    scope,
                    content["created_at"],
                    item["ticker"],
                    item["decision"],
                    item["policy_outcome"],
                    item["lifecycle"],
                    item["public_summary"],
                    encoded,
                    feed_encoded,
                )
                if existing:
                    target.execute(
                        "UPDATE public_decisions SET portfolio_id=?, created_at=?, ticker=?, "
                        "action=?, policy=?, lifecycle=?, summary=?, content=?, "
                        "feed_content=?, withdrawn=0 "
                        "WHERE source_key=?",
                        (*values, key),
                    )
                    counts["updated"] += 1
                else:
                    target.execute(
                        "INSERT INTO public_decisions (source_key, public_id, portfolio_id, "
                        "created_at, ticker, action, policy, lifecycle, summary, content, "
                        "feed_content) VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, public_id, *values),
                    )
                    counts["inserted"] += 1
            withdrawal_keys = (
                [
                    hashlib.sha256(row[0].encode()).hexdigest()
                    for row in source.execute(
                        "SELECT decision_id FROM publication_decision_changes WHERE revision>?",
                        (previous["changes"][1],),
                    )
                ]
                if partial_details and previous
                else [
                    row[0]
                    for row in target.execute(
                        "SELECT source_key FROM public_decisions WHERE withdrawn=0"
                    )
                ]
            )
            for key in withdrawal_keys:
                if key not in seen:
                    counts["withdrawn"] += target.execute(
                        "UPDATE public_decisions SET withdrawn=1 WHERE source_key=? AND "
                        "withdrawn=0",
                        (key,),
                    ).rowcount
            if counts["updated"] or counts["withdrawn"]:
                target.execute("UPDATE publication_meta SET revision = revision + 1")
            target.execute("UPDATE publication_meta SET updated_at = ?", (now,))
            decision_counts: dict[str, dict[str, int]] = {}
            decision_day = published_at.astimezone(NEW_YORK).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            decision_count_date = decision_day.date().isoformat()
            decisions_today: dict[str, int] = {}
            for scope in ("live", "paper"):
                scope_counts = {"approved": 0, "rejected": 0, "unavailable": 0}
                for policy, count in target.execute(
                    "SELECT policy, COUNT(*) FROM public_decisions WHERE portfolio_id=? "
                    "AND revoked=0 AND withdrawn=0 GROUP BY policy",
                    (scope,),
                ):
                    scope_counts[policy] = count
                decision_counts[scope] = scope_counts
                decisions_today[scope] = target.execute(
                    "SELECT COUNT(*) FROM public_decisions WHERE portfolio_id=? AND "
                    "revoked=0 AND withdrawn=0 AND created_at>=? AND created_at<?",
                    (
                        scope,
                        decision_day.astimezone(UTC).isoformat(),
                        (decision_day + timedelta(days=1)).astimezone(UTC).isoformat(),
                    ),
                ).fetchone()[0]
                target.execute(
                    "UPDATE public_portfolios SET content=json_set(content, "
                    "'$.decision_counts', json(?), '$.decision_count_date', ?, "
                    "'$.decisions_today', ?) WHERE portfolio_id=?",
                    (
                        json.dumps(scope_counts, sort_keys=True),
                        decision_count_date,
                        decisions_today[scope],
                        scope,
                    ),
                )
            if not performance_changed:
                return counts
            live: dict[str, Any] = {
                "portfolio_id": "live",
                "name": "BouStrategy",
                "mode": "live",
                "is_default": True,
                "status": "available" if latest_live else "unavailable",
                "reason": None if latest_live else "no_published_live_snapshot",
                "data_as_of": latest_live["captured_at"] if latest_live else None,
                "equity": latest_live["account_equity"] if latest_live else None,
                "cash": None,
                "return_percent": None,
                "history": [],
                "positions": [
                    {
                        "ticker": p["ticker"],
                        "market_value": p["market_value"],
                        "weight": p["market_value"] / latest_live["account_equity"],
                        "theme": p.get("primary_theme_id") or None,
                        "shares": None,
                        "average_cost": None,
                        "latest_price": None,
                    }
                    for p in latest_live["positions"]
                ]
                if latest_live
                else [],
                "capabilities": {"returns": False, "cash": False, "quantities": False},
            }
            # Paper positions are materialized only at publication, not on v2 GET.
            paper_status, paper_equity, paper_positions = "unavailable", None, []
            has_paper_data = bool(
                table_exists(source, "paper_positions")
                and source.execute("SELECT 1 FROM paper_positions LIMIT 1").fetchone()
            ) or bool(
                table_exists(source, "paper_fills")
                and source.execute("SELECT 1 FROM paper_fills LIMIT 1").fetchone()
            )
            if has_paper_data and table_exists(source, "order_intents"):
                contaminated = source.execute(
                    "SELECT 1 FROM paper_fills f LEFT JOIN order_intents o "
                    "USING(order_intent_id) WHERE o.order_intent_id IS NULL OR "
                    "o.execution_mode!='PAPER' LIMIT 1"
                ).fetchone()
                if contaminated:
                    has_paper_data = False
            if has_paper_data:
                rows = source.execute(
                    "SELECT ticker, shares, avg_cost, primary_theme_id FROM "
                    "paper_positions ORDER BY ticker"
                ).fetchall()
                valued: list[tuple[str, float, float, str, float | None]] = []
                for ticker, shares, average_cost, theme in rows:
                    price_row = (
                        source.execute(
                            "SELECT close FROM daily_prices WHERE ticker = ? "
                            "ORDER BY bar_date DESC LIMIT 1",
                            (ticker,),
                        ).fetchone()
                        if table_exists(source, "daily_prices")
                        else None
                    )
                    price = float(price_row[0]) if price_row else None
                    valued.append(
                        (str(ticker), float(shares), float(average_cost), str(theme), price)
                    )
                paper_equity = (
                    cash_balance(source)
                    + sum(shares * price for _, shares, _, _, price in valued if price is not None)
                    if all(price is not None for _, _, _, _, price in valued)
                    else None
                )
                for ticker, shares, average_cost, theme, price in valued:
                    value = float(shares) * price if price is not None else None
                    paper_positions.append(
                        {
                            "ticker": str(ticker),
                            "shares": float(shares),
                            "average_cost": float(average_cost),
                            "latest_price": price,
                            "market_value": value,
                            "weight": value / paper_equity
                            if value is not None and paper_equity
                            else None,
                            "unrealized_return_percent": ((price / float(average_cost)) - 1) * 100
                            if price is not None and average_cost
                            else None,
                            "theme": str(theme) or None,
                            "latest_public_summary": None,
                        }
                    )
                paper_status = "available" if paper_equity is not None else "unavailable"
            paper_view: dict[str, Any] = {
                "portfolio_id": "paper",
                "name": "BouStrategy paper",
                "mode": "paper",
                "is_default": False,
                "status": paper_status,
                "reason": None,
                "data_as_of": None,
                "equity": paper_equity,
                "return_percent": None,
                "history": [],
                "positions": paper_positions,
                "cash": None,
                "capabilities": {"returns": False, "cash": False, "quantities": True},
            }
            if latest_live:
                live.update(
                    status="partial",
                    reason="legacy_snapshot_missing_reporting_facts",
                    holdings_status="available",
                    portfolio_state="observed_holdings"
                    if latest_live["positions"]
                    else "zero_positions_cash_unknown",
                    last_complete_valuation=None,
                    currency="USD",
                )
            paper_view["simulation_convention"] = (
                "New next_open_v2 fills size holdings at contemporaneous opens; legacy_close_v1 "
                "fills retain original close-based sizing. No fees, slippage, dividends or "
                "corporate actions are simulated."
            )
            for portfolio in (live, paper_view):
                portfolio["decision_counts"] = decision_counts[portfolio["mode"]]
                portfolio["decision_count_date"] = decision_count_date
                portfolio["decisions_today"] = decisions_today[portfolio["mode"]]
                reporting: dict[str, Any] = {}
                ranges: dict[str, dict[str, Any]] = {}
                observations = reporting_by_scope[portfolio["mode"]]
                paper_issue = None
                if portfolio["mode"] == "paper":
                    reconstructed, paper_issue = paper_observations(
                        source, observed_at=published_at
                    )
                    if not observations:
                        observations = reconstructed
                if observations:
                    reporting, ranges = materialize(source, observations)
                if paper_issue:
                    reporting = {
                        "status": "unavailable",
                        "reason": paper_issue,
                        "equity": None,
                        "cash": None,
                        "positions": [],
                        "return_percent": None,
                        "capabilities": {"returns": False, "cash": False, "quantities": False},
                        "data_as_of": None,
                    }
                    ranges = {}
                if reporting and (
                    not portfolio.get("data_as_of")
                    or (
                        reporting.get("data_as_of") is not None
                        and datetime.fromisoformat(reporting["data_as_of"])
                        >= datetime.fromisoformat(portfolio["data_as_of"])
                    )
                ):
                    portfolio.update(reporting)
                for range_name in ("1M", "3M", "YTD", "All"):
                    performance = ranges.get(range_name) or {
                        "range": range_name,
                        "status": "unavailable",
                        "reason": "reporting_history_missing",
                        "return_percent": None,
                        "history": [],
                        "benchmarks": [],
                        "start_at": None,
                        "end_at": None,
                    }
                    target.execute(
                        "INSERT INTO public_performance VALUES (?, ?, ?) ON "
                        "CONFLICT(portfolio_id, range_name) DO UPDATE SET content=excluded.content",
                        (
                            portfolio["portfolio_id"],
                            range_name,
                            json.dumps(performance, sort_keys=True),
                        ),
                    )
                episodes = portfolio.get("holding_episodes", {}).get("items", [])
                full_episodes = episodes
                if observations and not paper_issue:
                    episode_values = sorted(
                        [
                            o
                            for o in observations
                            if isinstance(o, ValuationObservation)
                            and o.phase not in {"before_flow", "after_flow"}
                        ],
                        key=lambda o: o.occurred_at,
                    )
                    if episode_values:
                        full_episodes = holding_episodes(
                            episode_values,
                            observations,
                            [o for o in observations if isinstance(o, CoverageObservation)],
                            limit=None,
                        )["items"]
                review_account = reporting_account if portfolio["mode"] == "live" else "paper"
                for episode in full_episodes:
                    episode["thesis_review"] = explanations.thesis_projection(
                        reviews.get(
                            (portfolio["mode"], review_account or "", episode["episode_id"])
                        ),
                        sources,
                    )
                by_episode = {item["episode_id"]: item for item in full_episodes}
                for episode in episodes:
                    episode["thesis_review"] = by_episode[episode["episode_id"]]["thesis_review"]
                for position in portfolio["positions"]:
                    episode = next(
                        (
                            item
                            for item in full_episodes
                            if item["ticker"] == position["ticker"] and item["status"] == "open"
                        ),
                        None,
                    )
                    position["holding_episode_id"] = episode["episode_id"] if episode else None
                    position["thesis_review"] = (
                        episode["thesis_review"]
                        if episode
                        else explanations.thesis_projection(None, sources)
                    )
                    latest = target.execute(
                        "SELECT public_id, summary FROM public_decisions WHERE portfolio_id=? "
                        "AND ticker=? AND revoked=0 AND withdrawn=0 ORDER BY created_at DESC, "
                        "public_id DESC LIMIT 1",
                        (portfolio["portfolio_id"], position["ticker"]),
                    ).fetchone()
                    position["latest_public_summary"] = latest[1] if latest else None
                    position["latest_decision_id"] = latest[0] if latest else None
                policy_catalog = catalog()
                policy_catalog["current_exposure"] = [
                    {
                        "ticker": p["ticker"],
                        "weight": p.get("weight"),
                        "as_of": portfolio.get("data_as_of"),
                        "interpretation": "observed_exposure_not_entry_policy_verdict",
                    }
                    for p in portfolio["positions"]
                ]
                theme_weights: dict[str, float] = {}
                for position in portfolio["positions"]:
                    if position.get("weight") is not None:
                        theme = position.get("theme") or "unclassified"
                        theme_weights[theme] = theme_weights.get(theme, 0.0) + position["weight"]
                policy_catalog["current_theme_exposure"] = [
                    {"theme": name, "weight": weight} for name, weight in theme_weights.items()
                ]
                policy_catalog["current_asset_exposure"] = portfolio.get("allocation", [])
                target.execute(
                    "INSERT INTO public_policy VALUES (?, ?) ON CONFLICT(portfolio_id) "
                    "DO UPDATE SET content=excluded.content",
                    (portfolio["portfolio_id"], json.dumps(policy_catalog, sort_keys=True)),
                )
                target.execute(
                    "INSERT INTO public_portfolios VALUES (?, ?) ON CONFLICT(portfolio_id) DO "
                    "UPDATE SET content=excluded.content",
                    (portfolio["portfolio_id"], json.dumps(portfolio, sort_keys=True)),
                )
        return counts
    finally:
        target.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--public-db", required=True)
    parser.add_argument("--live-profile", action="append", default=[])
    parser.add_argument("--live-account-id")
    parser.add_argument("--watch", type=float, metavar="SECONDS")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.watch is not None and not 0.1 <= args.watch <= 60:
        parser.error("--watch must be 0.1 through 60 seconds")
    if Path(args.source).resolve() == Path(args.public_db).resolve():
        raise ValueError("public store must be separate from source")
    if not Path(args.source).is_file():
        raise FileNotFoundError("source database does not exist")
    if args.watch is not None:
        from app.storage.database import connect

        source = connect(args.source, wal=True)
        source.close()
    while True:
        print(
            json.dumps(
                publish(
                    args.source,
                    args.public_db,
                    live_profiles=tuple(args.live_profile),
                    live_account_id=args.live_account_id,
                    rebuild=args.rebuild,
                )
            ),
            flush=True,
        )
        args.rebuild = False
        if args.watch is None:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
