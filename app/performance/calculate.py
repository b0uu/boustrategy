"""Exact USD accounting from complete, explicitly covered observations."""

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any

from app.schemas.reporting import CoverageObservation, FlowObservation, ValuationObservation
from app.x.calendar import NEW_YORK, CalendarCoverageError, previous_session, session_close

METHODOLOGY = {
    "version": "reporting-v1",
    "currency": "USD",
    "money_precision": "0.01",
    "rounding": "half_even",
    "return": "Linked returns with complete valuations on both sides of every external flow.",
    "fees_and_dividends": "Included in investment return through observed account equity.",
    "external_activity": "Cash and security transfers are external flows at recorded fair value.",
    "drawdown": "Observed session-close drawdown of flow-adjusted wealth; not intraday drawdown.",
    "daily_pnl": "Equity change from the recorded prior session close, less external flows.",
    "session_calendar_binding": "nyse-2026-2028-v1",
    "coverage": "Missing external-flow coverage suppresses returns.",
}


def covered(
    start: datetime, end: datetime, coverage: list[CoverageObservation], *, activity: bool = False
) -> bool:
    if start == end:
        return True
    through = start
    for item in sorted(coverage, key=lambda item: item.start_at):
        if not (item.activity_complete if activity else item.external_flows_complete):
            continue
        if item.start_at <= through < item.end_at:
            through = item.end_at
        if through >= end:
            return True
    return False


def linked_return(
    start: ValuationObservation,
    end: ValuationObservation,
    valuations: dict[str, ValuationObservation],
    flows: list[FlowObservation],
    coverage: list[CoverageObservation],
) -> dict[str, Any]:
    if (start.mode, start.account_id) != (end.mode, end.account_id):
        raise ValueError("return endpoints must share one account")
    if any(
        (item.mode, item.account_id) != (start.mode, start.account_id)
        for item in [*valuations.values(), *flows, *coverage]
    ):
        raise ValueError("return inputs must share one account")
    if start.phase in {"before_flow", "after_flow"} or end.phase in {"before_flow", "after_flow"}:
        return {
            "status": "unavailable",
            "reason": "flow_boundary_endpoint_unsupported",
            "return_percent": None,
        }
    if any(flow.occurred_at in {start.occurred_at, end.occurred_at} for flow in flows):
        return {
            "status": "unavailable",
            "reason": "coincident_flow_endpoint_order_unknown",
            "return_percent": None,
        }
    if start.observation_id == end.observation_id:
        # One complete valuation spans no interval. Nothing changed across it, which is a
        # measured zero rather than a missing fact; a newly funded account is not "unknown".
        if not start.complete:
            return {
                "status": "unavailable",
                "reason": "incomplete_valuation",
                "return_percent": None,
            }
        return {"status": "available", "reason": "single_observation", "return_percent": 0.0}
    if start.occurred_at >= end.occurred_at:
        return {
            "status": "unavailable",
            "reason": "insufficient_observations",
            "return_percent": None,
        }
    if not start.complete or not end.complete:
        return {"status": "unavailable", "reason": "incomplete_valuation", "return_percent": None}
    if not covered(start.occurred_at, end.occurred_at, coverage):
        return {
            "status": "unavailable",
            "reason": "external_flow_coverage_missing",
            "return_percent": None,
        }
    assert start.equity is not None and end.equity is not None
    events = sorted(
        (flow for flow in flows if start.occurred_at < flow.occurred_at <= end.occurred_at),
        key=lambda flow: (flow.occurred_at, flow.sequence, flow.observation_id),
    )
    if len({(flow.occurred_at, flow.sequence) for flow in events}) != len(events):
        return {
            "status": "unavailable",
            "reason": "simultaneous_flow_order_unknown",
            "return_percent": None,
        }
    boundary_ids = [
        identifier
        for flow in events
        for identifier in (flow.before_valuation_id, flow.after_valuation_id)
        if identifier is not None
    ]
    if len(set(boundary_ids)) != len(boundary_ids):
        return {
            "status": "unavailable",
            "reason": "external_flow_boundary_reused",
            "return_percent": None,
        }
    previous_flow_at = None
    factor = Decimal(1)
    previous = start.equity
    funded = previous > 0
    with localcontext() as context:
        context.prec = 40
        for flow in events:
            before = valuations.get(flow.before_valuation_id or "")
            after = valuations.get(flow.after_valuation_id or "")
            if before is None or after is None or not before.complete or not after.complete:
                return {
                    "status": "unavailable",
                    "reason": "external_flow_boundary_missing",
                    "return_percent": None,
                }
            assert before.equity is not None and after.equity is not None
            if (
                before.phase != "before_flow"
                or after.phase != "after_flow"
                or before.occurred_at != flow.occurred_at
                or after.occurred_at != flow.occurred_at
                or after.equity - before.equity != flow.amount
            ):
                return {
                    "status": "unavailable",
                    "reason": "external_flow_boundary_mismatch",
                    "return_percent": None,
                }
            if previous_flow_at == flow.occurred_at and before.equity != previous:
                return {
                    "status": "unavailable",
                    "reason": "simultaneous_flow_boundary_gap",
                    "return_percent": None,
                }
            previous_flow_at = flow.occurred_at
            if previous == 0:
                if before.equity != 0:
                    return {
                        "status": "unavailable",
                        "reason": "zero_return_base",
                        "return_percent": None,
                    }
            else:
                factor *= before.equity / previous
            previous = after.equity
            funded = funded or previous > 0
        if previous == 0:
            if end.equity != 0 or not funded:
                return {
                    "status": "unavailable",
                    "reason": "zero_return_base",
                    "return_percent": None,
                }
        else:
            factor *= end.equity / previous
        if factor.adjusted() >= context.prec - 8:
            return {
                "status": "unavailable",
                "reason": "return_precision_exceeded",
                "return_percent": None,
            }
        return {
            "status": "available",
            "reason": None,
            "return_percent": str(((factor - 1) * 100).quantize(Decimal("0.000001"))),
            "growth_factor": str(factor),
            "net_external_flows": str(
                sum((flow.amount for flow in events), Decimal(0)).quantize(Decimal("0.01"))
            ),
            "investment_pnl": str(
                (
                    end.equity - start.equity - sum((flow.amount for flow in events), Decimal(0))
                ).quantize(Decimal("0.01"))
            ),
        }


def session_timestamp_reason(value: ValuationObservation) -> str | None:
    if value.session_date is None:
        return "session_date_missing"
    try:
        close = session_close(value.session_date)
    except CalendarCoverageError:
        return "session_calendar_out_of_coverage"
    if close is None:
        return "session_not_eligible"
    if value.occurred_at.astimezone(NEW_YORK).date() != value.session_date:
        return "session_timestamp_mismatch"
    if value.phase == "session_close" and value.occurred_at < close:
        return "valuation_precedes_session_close"
    return None


def daily_pnl(
    latest: ValuationObservation,
    values: list[ValuationObservation],
    flows: list[FlowObservation],
    coverage: list[CoverageObservation],
) -> dict[str, Any]:
    reason = session_timestamp_reason(latest)
    if reason:
        return {"status": "unavailable", "reason": reason, "amount": None}
    try:
        expected = previous_session(latest.session_date) if latest.session_date else None
        expected_close = session_close(expected) if expected else None
    except CalendarCoverageError:
        return {
            "status": "unavailable",
            "reason": "session_calendar_out_of_coverage",
            "amount": None,
        }
    if latest.previous_session_date is not None and latest.previous_session_date != expected:
        return {"status": "unavailable", "reason": "previous_session_date_mismatch", "amount": None}
    baseline = (
        next(
            (
                value
                for value in reversed(values)
                if value.phase == "session_close"
                and value.session_date == expected
                and value.occurred_at < latest.occurred_at
            ),
            None,
        )
        if expected
        else None
    )
    if baseline is None:
        return {"status": "unavailable", "reason": "prior_session_close_missing", "amount": None}
    baseline_reason = session_timestamp_reason(baseline)
    if baseline_reason:
        return {"status": "unavailable", "reason": baseline_reason, "amount": None}
    if expected_close is None or baseline.occurred_at < expected_close:
        return {
            "status": "unavailable",
            "reason": "baseline_precedes_session_close",
            "amount": None,
        }
    if latest.phase in {"before_flow", "after_flow"} or any(
        flow.occurred_at in {baseline.occurred_at, latest.occurred_at} for flow in flows
    ):
        return {
            "status": "unavailable",
            "reason": "coincident_flow_endpoint_order_unknown",
            "amount": None,
        }
    if not baseline.complete or not latest.complete:
        return {"status": "unavailable", "reason": "incomplete_valuation", "amount": None}
    if not covered(baseline.occurred_at, latest.occurred_at, coverage):
        return {"status": "unavailable", "reason": "external_flow_coverage_missing", "amount": None}
    assert latest.equity is not None and baseline.equity is not None
    net_flows = sum(
        (
            flow.amount
            for flow in flows
            if baseline.occurred_at < flow.occurred_at <= latest.occurred_at
        ),
        Decimal(0),
    )
    return {
        "status": "available",
        "reason": None,
        "amount": str(latest.equity - baseline.equity - net_flows),
        "net_external_flows": str(net_flows),
        "baseline_at": baseline.occurred_at.isoformat(),
    }
