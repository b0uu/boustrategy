"""Trusted, immutable reporting ingestion. Callers own the transaction."""

import argparse
import json
import sqlite3
from datetime import UTC
from pathlib import Path

from app.schemas.reporting import (
    OBSERVATION_ADAPTER,
    CorporateActionObservation,
    FillObservation,
    FlowObservation,
    ReportingObservation,
    ValuationObservation,
)
from app.storage.database import connect


def ingest(conn: sqlite3.Connection, observation: ReportingObservation) -> bool:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    encoded = observation.model_dump_json()
    existing = conn.execute(
        "SELECT observation_json FROM reporting_observations WHERE observation_id=?",
        (observation.observation_id,),
    ).fetchone()
    if existing:
        if OBSERVATION_ADAPTER.validate_json(existing[0]) == observation:
            return False
        raise ValueError("observation ID already has different content")
    if observation.supersedes:
        previous = conn.execute(
            "SELECT observation_json FROM reporting_observations WHERE observation_id=?",
            (observation.supersedes,),
        ).fetchone()
        if previous is None:
            raise ValueError("correction target does not exist")
        prior = OBSERVATION_ADAPTER.validate_json(previous[0])
        if (prior.mode, prior.account_id, prior.kind, prior.external_event_id) != (
            observation.mode,
            observation.account_id,
            observation.kind,
            observation.external_event_id,
        ):
            raise ValueError("correction cannot change account, kind or external identity")
        if observation.recorded_at < prior.recorded_at:
            raise ValueError("correction cannot precede the previous observation")
        if conn.execute(
            "SELECT 1 FROM reporting_observations WHERE supersedes=?", (observation.supersedes,)
        ).fetchone():
            raise ValueError("correction target is already superseded")
    elif conn.execute(
        "SELECT 1 FROM reporting_observations WHERE mode=? AND account_id=? AND kind=? AND "
        "external_event_id=?",
        (observation.mode, observation.account_id, observation.kind, observation.external_event_id),
    ).fetchone():
        raise ValueError("external event already exists; submit an explicit correction")
    if isinstance(observation, ValuationObservation) and observation.phase not in {
        "before_flow",
        "after_flow",
    }:
        valuation_rows = conn.execute(
            "SELECT observation_json FROM reporting_observations parent WHERE mode=? "
            "AND account_id=? AND kind='valuation' AND occurred_at=? AND voided=0 "
            "AND NOT EXISTS (SELECT 1 FROM reporting_observations child "
            "WHERE child.supersedes=parent.observation_id)",
            (
                observation.mode,
                observation.account_id,
                observation.occurred_at.astimezone(UTC).isoformat(),
            ),
        )
        for row in valuation_rows:
            other = OBSERVATION_ADAPTER.validate_json(row[0])
            if (
                isinstance(other, ValuationObservation)
                and other.phase not in {"before_flow", "after_flow"}
                and other.observation_id != observation.supersedes
            ):
                raise ValueError("valuation instant already exists; use an explicit correction")
    if isinstance(observation, FillObservation) and observation.decision_id:
        intent = conn.execute(
            "SELECT execution_mode, execution_profile_id, ticker, side FROM order_intents WHERE "
            "decision_id=?",
            (observation.decision_id,),
        ).fetchone()
        if intent is None or (intent[0].lower(), intent[2], intent[3]) != (
            observation.mode,
            observation.ticker,
            observation.side,
        ):
            raise ValueError("fill decision has no matching execution mode")
        if observation.mode == "live":
            accounts = {
                json.loads(row[0])["broker_account_fingerprint"]
                for row in conn.execute(
                    "SELECT snapshot_json FROM live_portfolio_snapshots WHERE "
                    "execution_profile_id=?",
                    (intent[1],),
                )
            }
            if accounts != {observation.account_id}:
                raise ValueError("fill decision account linkage is missing or ambiguous")
    if isinstance(observation, FlowObservation):
        boundaries: list[ValuationObservation] = []
        for reference, phase in (
            (observation.before_valuation_id, "before_flow"),
            (observation.after_valuation_id, "after_flow"),
        ):
            if reference is None:
                continue
            row = conn.execute(
                "SELECT observation_json FROM reporting_observations WHERE observation_id=? AND "
                "voided=0 AND NOT EXISTS (SELECT 1 FROM reporting_observations child WHERE "
                "child.supersedes=reporting_observations.observation_id)",
                (reference,),
            ).fetchone()
            if row is None:
                raise ValueError("flow boundary is absent or superseded")
            boundary = OBSERVATION_ADAPTER.validate_json(row[0])
            if not isinstance(boundary, ValuationObservation) or (
                boundary.mode,
                boundary.account_id,
                boundary.occurred_at,
                boundary.phase,
            ) != (observation.mode, observation.account_id, observation.occurred_at, phase):
                raise ValueError("flow boundary does not match account, instant and phase")
            boundaries.append(boundary)
        if len(boundaries) == 2 and all(v.equity is not None for v in boundaries):
            before, after = boundaries
            assert before.equity is not None and after.equity is not None
            if after.equity - before.equity != observation.amount:
                raise ValueError("flow boundary equities do not reconcile to external flow")
    if isinstance(observation, CorporateActionObservation) and observation.flow_external_id:
        rows = conn.execute(
            "SELECT observation_json FROM reporting_observations WHERE mode=? AND account_id=? "
            "AND kind='flow' AND external_event_id=? AND voided=0 AND NOT EXISTS (SELECT 1 FROM "
            "reporting_observations child WHERE "
            "child.supersedes=reporting_observations.observation_id)",
            (observation.mode, observation.account_id, observation.flow_external_id),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("security transfer requires its external flow observation")
        flow = OBSERVATION_ADAPTER.validate_json(rows[0][0])
        if (
            not isinstance(flow, FlowObservation)
            or flow.flow_type != observation.action
            or flow.occurred_at != observation.occurred_at
        ):
            raise ValueError("security transfer does not match linked flow")
    conn.execute(
        "INSERT INTO reporting_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            observation.observation_id,
            observation.mode,
            observation.account_id,
            observation.kind,
            observation.external_event_id,
            observation.occurred_at.astimezone(UTC).isoformat(),
            observation.recorded_at.astimezone(UTC).isoformat(),
            observation.supersedes,
            observation.voided,
            encoded,
        ),
    )
    return True


def current_observations(
    conn: sqlite3.Connection, *, mode: str, account_id: str
) -> list[ReportingObservation]:
    return [
        OBSERVATION_ADAPTER.validate_json(row[0])
        for row in conn.execute(
            "SELECT observation_json FROM reporting_observations parent WHERE mode=? AND "
            "account_id=? "
            "AND voided=0 AND NOT EXISTS (SELECT 1 FROM reporting_observations child "
            "WHERE child.supersedes=parent.observation_id) ORDER BY occurred_at, observation_id",
            (mode, account_id),
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest trusted reporting JSON; never calls a broker"
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--mode", required=True, choices=("live", "paper"))
    parser.add_argument("--account-id", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    observations = [OBSERVATION_ADAPTER.validate_python(item) for item in payload]
    if any(item.mode != args.mode or item.account_id != args.account_id for item in observations):
        parser.error("input observations do not match the requested reporting account")
    conn = connect(args.db)
    try:
        with conn:
            inserted = sum(ingest(conn, item) for item in observations)
        print(json.dumps({"inserted": inserted, "unchanged": len(observations) - inserted}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
