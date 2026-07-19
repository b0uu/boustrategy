import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from app.paper.context import portfolio_context
from app.state.pipeline import DecisionStatus, ProcessOutcome, process_decision
from app.storage.database import connect
from app.triggers.store import mark_triggers

from .intake import build_intake

_CONSIDERED_STATUSES = {
    DecisionStatus.POLICY_APPROVED,
    DecisionStatus.POLICY_REJECTED,
    DecisionStatus.ORDER_INTENT_CREATED,
}


def submit_decision(
    conn: sqlite3.Connection,
    record_data: dict[str, Any],
    on_date: date,
    consume_trigger_ids: list[str] | None = None,
) -> ProcessOutcome:
    raw_ticker = record_data.get("ticker")
    ticker = raw_ticker if isinstance(raw_ticker, str) else None
    portfolio = portfolio_context(conn, on_date, exclude_ticker=ticker)
    outcome = process_decision(conn, record_data, portfolio)
    if consume_trigger_ids and outcome.final_status in _CONSIDERED_STATUSES:
        mark_triggers(conn, consume_trigger_ids, "consumed")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.reason.run")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake_parser = subparsers.add_parser("intake")
    intake_parser.add_argument("--date")
    intake_parser.add_argument("--out", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--in", dest="input_path", required=True)
    submit_parser.add_argument("--date")
    submit_parser.add_argument("--consume-triggers")

    args = parser.parse_args()
    conn = connect(args.db)
    on_date = date.fromisoformat(args.date) if args.date else date.today()
    if args.command == "intake":
        print(build_intake(conn, on_date, args.out))
    else:
        record_data = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
        trigger_ids = args.consume_triggers.split(",") if args.consume_triggers else []
        outcome = submit_decision(conn, record_data, on_date, trigger_ids)
        print(outcome.model_dump_json())


if __name__ == "__main__":
    main()
