"""Immutable input binding for completed deterministic policy evaluations."""

import hashlib
import json
import sqlite3
from datetime import datetime

from app.policy.catalog import POLICY_VERSION, VALIDATOR_VERSION
from app.policy.decision_policy import PolicyResult, PortfolioContext
from app.schemas.decision_record import InvestmentDecisionRecord, RegimeState
from app.schemas.order_intent import ExecutionMode
from app.schemas.policy_reporting import PolicyEvaluationRecord, PolicyInputIdentity, RecordedRegime


def save_policy_evaluation(
    conn: sqlite3.Connection,
    record: InvestmentDecisionRecord,
    result: PolicyResult,
    portfolio: PortfolioContext | None,
    truth: RegimeState | None,
    evaluated_at: datetime,
    identity: PolicyInputIdentity | None,
    execution_mode: ExecutionMode,
    execution_profile_id: str,
) -> PolicyEvaluationRecord:
    identity = identity or PolicyInputIdentity()
    regime = None
    if identity.regime_snapshot_id:
        row = conn.execute(
            "SELECT snapshot_date, regime, raw_regime, score, components_json, computed_at "
            "FROM regime_snapshots WHERE snapshot_date=?",
            (identity.regime_snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("policy regime snapshot is missing")
        regime = RecordedRegime(
            snapshot_date=row[0],
            state=row[1],
            raw_state=row[2],
            score=row[3],
            components=json.loads(row[4]),
            computed_at=row[5],
        )
        if (
            identity.regime_snapshot_hash
            and hashlib.sha256(json.dumps(list(row)).encode()).hexdigest()
            != identity.regime_snapshot_hash
        ):
            raise ValueError("policy regime snapshot changed after it was selected")
        if regime.computed_at > evaluated_at or regime.state != truth:
            raise ValueError("policy regime snapshot does not match evaluation time or input")
    portfolio_snapshot = None
    if identity.portfolio_snapshot_id:
        row = conn.execute(
            "SELECT snapshot_json FROM live_portfolio_snapshots WHERE portfolio_snapshot_id=?",
            (identity.portfolio_snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("policy portfolio snapshot is missing")
        portfolio_snapshot = json.loads(row[0])
        if (
            execution_mode != ExecutionMode.LIVE
            or portfolio_snapshot["execution_profile_id"] != execution_profile_id
        ):
            raise ValueError("policy portfolio snapshot does not match execution profile")
        positions = [p for p in portfolio_snapshot["positions"] if p["market_value"] > 0]
        weights: dict[str, float] = {}
        for position in positions:
            if position["ticker"] != record.ticker:
                theme = position["primary_theme_id"]
                weights[theme] = (
                    weights.get(theme, 0.0)
                    + position["market_value"] / portfolio_snapshot["account_equity"]
                )
        if (
            portfolio is None
            or portfolio.holdings_count != len(positions)
            or weights.keys() != portfolio.primary_theme_weights.keys()
            or any(
                abs(weight - portfolio.primary_theme_weights[theme]) > 1e-9
                for theme, weight in weights.items()
            )
        ):
            raise ValueError("portfolio facts contradict the bound snapshot")
        if datetime.fromisoformat(portfolio_snapshot["captured_at"]) > evaluated_at:
            raise ValueError("policy portfolio snapshot follows evaluation")
        weight = (
            sum(
                position["market_value"]
                for position in portfolio_snapshot["positions"]
                if position["ticker"] == record.ticker
            )
            / portfolio_snapshot["account_equity"]
        )
        if identity.current_weight is not None and abs(identity.current_weight - weight) > 1e-9:
            raise ValueError("current weight does not match bound snapshot")
    evaluation = PolicyEvaluationRecord(
        decision_id=record.decision_id,
        execution_mode=execution_mode,
        execution_profile_id=execution_profile_id,
        evaluated_at=evaluated_at,
        policy_version=POLICY_VERSION,
        validator_version=VALIDATOR_VERSION,
        validator_schema_sha256=hashlib.sha256(
            json.dumps(InvestmentDecisionRecord.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
        authored_schema_version=record.schema_version,
        approved=result.approved,
        reasons=result.reasons,
        checks=result.checks,
        portfolio=portfolio,
        true_regime_state=truth,
        input_identity=identity,
        regime_snapshot=regime,
        portfolio_snapshot=portfolio_snapshot,
    )
    existing = conn.execute(
        "SELECT evaluation_json FROM policy_evaluations WHERE decision_id=?", (record.decision_id,)
    ).fetchone()
    if existing:
        if PolicyEvaluationRecord.model_validate_json(existing[0]) != evaluation:
            raise ValueError("policy evaluation is immutable")
        return evaluation
    conn.execute(
        "INSERT INTO policy_evaluations VALUES (?, ?, ?, ?)",
        (
            record.decision_id,
            evaluated_at.isoformat(),
            POLICY_VERSION,
            evaluation.model_dump_json(),
        ),
    )
    return evaluation
