import argparse
import json
from pathlib import Path

from app.broker.lifecycle import append_execution_event
from app.schemas.broker_execution import BrokerExecutionEvent, BrokerExecutionRecord
from app.storage.database import connect
from app.storage.records import save_broker_execution_record


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.broker.run")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--in", dest="input_path", required=True)

    event_parser = subparsers.add_parser("event")
    event_parser.add_argument("--in", dest="input_path", required=True)

    args = parser.parse_args()
    payload = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
    conn = connect(args.db)
    if args.command == "record":
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
    else:
        event = BrokerExecutionEvent.model_validate(payload)
        created = append_execution_event(conn, event)
        print(json.dumps({"created": created, "broker_event_id": event.broker_event_id}))


if __name__ == "__main__":
    main()
