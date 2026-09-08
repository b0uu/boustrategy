import argparse
import getpass
import json
from contextlib import closing
from pathlib import Path

from app.broker.config import account_fingerprint, get_live_profile, load_live_profiles
from app.broker.lifecycle import append_execution_event
from app.broker.packet import build_execution_packet
from app.schemas.broker_execution import BrokerExecutionEvent, BrokerExecutionRecord
from app.schemas.live_execution import BrokerPreflight, LivePortfolioSnapshot
from app.storage.database import connect
from app.storage.records import (
    get_decision_record,
    get_order_intent,
    save_broker_execution_record,
    save_execution_packet,
    save_live_portfolio_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.broker.run")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--in", dest="input_path", required=True)

    event_parser = subparsers.add_parser("event")
    event_parser.add_argument("--in", dest="input_path", required=True)

    packet_parser = subparsers.add_parser("packet")
    packet_parser.add_argument("--intent-id", required=True)
    packet_parser.add_argument("--profiles", default="ops/live.local.json")
    packet_parser.add_argument("--preflight", required=True)

    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--in", dest="input_path", required=True)
    snapshot_parser.add_argument("--profiles", default="ops/live.local.json")

    subparsers.add_parser("fingerprint-account")

    args = parser.parse_args()
    if args.command == "fingerprint-account":
        identifier = getpass.getpass("Robinhood account identifier: ")
        print(account_fingerprint(identifier))
        return
    with closing(connect(args.db)) as conn:
        if args.command == "snapshot":
            snapshot = LivePortfolioSnapshot.model_validate_json(
                Path(args.input_path).read_text(encoding="utf-8")
            )
            config = load_live_profiles(args.profiles)
            profile = get_live_profile(config, snapshot.execution_profile_id)
            created = save_live_portfolio_snapshot(conn, snapshot, profile)
            print(
                json.dumps(
                    {
                        "created": created,
                        "portfolio_snapshot_id": snapshot.portfolio_snapshot_id,
                        "execution_profile_id": snapshot.execution_profile_id,
                    }
                )
            )
        elif args.command == "record":
            payload = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
            record = BrokerExecutionRecord.model_validate(payload)
            created = save_broker_execution_record(conn, record)
            print(
                json.dumps(
                    {
                        "created": created,
                        "broker_execution_record_id": record.broker_execution_record_id,
                    }
                )
            )
        elif args.command == "event":
            payload = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
            event = BrokerExecutionEvent.model_validate(payload)
            created = append_execution_event(conn, event)
            print(json.dumps({"created": created, "broker_event_id": event.broker_event_id}))
        else:
            intent = get_order_intent(conn, args.intent_id)
            if intent is None:
                raise ValueError(f"missing order intent {args.intent_id}")
            decision = get_decision_record(conn, intent.decision_id)
            if decision is None:
                raise ValueError(f"missing decision record {intent.decision_id}")
            config = load_live_profiles(args.profiles)
            profile = get_live_profile(config, intent.execution_profile_id)
            preflight = BrokerPreflight.model_validate_json(
                Path(args.preflight).read_text(encoding="utf-8")
            )
            packet = build_execution_packet(intent, decision, profile, preflight)
            created = save_execution_packet(conn, packet)
            print(json.dumps({"created": created, "packet": packet.model_dump(mode="json")}))


if __name__ == "__main__":
    main()
