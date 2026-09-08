"""Measure the real producer and source WAL writes on disposable synthetic history."""

import argparse
import json
import platform
import tempfile
from datetime import timedelta
from pathlib import Path
from statistics import median, quantiles
from threading import Event, Thread
from time import perf_counter
from unittest.mock import patch

from app.public.database import open_readonly
from app.public.publication import publish
from app.schemas.decision_record import InvestmentDecisionRecord
from app.schemas.order_intent import OrderIntent
from app.storage.database import connect
from app.storage.runtime import claim, heartbeat
from tests.fixtures.decision_records import valid_decision_record_data
from tests.reason.test_runtime import NOW, paper_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    args = parser.parse_args()
    if args.records < 1:
        parser.error("--records must be positive")
    with tempfile.TemporaryDirectory(prefix="bou-producer-") as folder:
        root = Path(folder)
        source, public = root / "source.db", root / "public.db"
        conn = connect(source, wal=True)
        template = InvestmentDecisionRecord.model_validate(valid_decision_record_data())
        for index in range(args.records):
            record = template.model_copy(update={"decision_id": f"synthetic_{index}"})
            conn.execute(
                "INSERT INTO decision_records(decision_id,created_at,ticker,decision,record_json) "
                "VALUES(?,?,?,?,?)",
                (
                    record.decision_id,
                    record.created_at.isoformat(),
                    record.ticker,
                    record.decision.value,
                    record.model_dump_json(),
                ),
            )
            intent = OrderIntent(
                order_intent_id=f"intent_{index}",
                decision_id=record.decision_id,
                created_at=record.created_at,
                ticker=record.ticker,
                side="BUY",
                order_type="MARKET",
                target_weight=0.12,
            )
            conn.execute(
                "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?)",
                (
                    intent.order_intent_id,
                    record.decision_id,
                    record.created_at.isoformat(),
                    record.ticker,
                    "BUY",
                    "PAPER",
                    "",
                    intent.model_dump_json(),
                ),
            )
        conn.commit()
        run = paper_run(conn, root)
        attempt = claim(conn, run.run_id, "offline-fixture", NOW)
        stop = Event()
        latencies: list[float] = []
        errors: list[str] = []

        def pulse_source() -> None:
            writer = connect(source)
            try:
                index = 0
                while not stop.wait(0.1):
                    index += 1
                    started = perf_counter()
                    try:
                        heartbeat(
                            writer,
                            attempt.attempt_id,
                            attempt.fence,
                            NOW + timedelta(seconds=index),
                        )
                    except Exception as error:
                        errors.append(type(error).__name__ + ": " + str(error))
                        return
                    latencies.append((perf_counter() - started) * 1000)
            finally:
                writer.close()

        thread = Thread(target=pulse_source)
        thread.start()
        started = perf_counter()
        try:
            initial = publish(source, public)
        finally:
            stop.set()
            thread.join(timeout=10)
        initial_seconds = perf_counter() - started
        assert initial["inserted"] == args.records and not errors and not thread.is_alive()
        # Catch up once after the concurrent producer, then measure a single dirty heartbeat.
        publish(source, public)
        previous = conn.execute("SELECT heartbeat_at FROM runtime_attempts").fetchone()[0]
        from datetime import datetime

        heartbeat(
            conn,
            attempt.attempt_id,
            attempt.fence,
            datetime.fromisoformat(previous) + timedelta(seconds=1),
        )
        validations = 0
        original = InvestmentDecisionRecord.model_validate_json

        def count(*args: object, **kwargs: object) -> InvestmentDecisionRecord:
            nonlocal validations
            validations += 1
            return original(*args, **kwargs)  # type: ignore[arg-type]

        started = perf_counter()
        with patch.object(InvestmentDecisionRecord, "model_validate_json", side_effect=count):
            delta = publish(source, public)
        heartbeat_ms = (perf_counter() - started) * 1000
        assert validations == 0 and not any(delta.values())
        conn.execute(
            "INSERT INTO status_events(subject_type,subject_id,status,occurred_at) "
            "VALUES('decision','synthetic_0','policy_rejected',?)",
            (NOW.isoformat(),),
        )
        conn.commit()
        started = perf_counter()
        with patch.object(InvestmentDecisionRecord, "model_validate_json", side_effect=count):
            changed = publish(source, public)
        decision_ms = (perf_counter() - started) * 1000
        assert validations == 1 and changed["updated"] == 1
        with open_readonly(public) as reader:
            assert (
                reader.execute("SELECT COUNT(*) FROM public_decisions").fetchone()[0]
                == args.records
            )
        conn.close()
        print(
            json.dumps(
                {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "records": args.records,
                    "initial_publication_seconds": round(initial_seconds, 3),
                    "source_heartbeat_count": len(latencies),
                    "source_heartbeat_p50_ms": round(median(latencies), 3) if latencies else None,
                    "source_heartbeat_p95_ms": round(quantiles(latencies, n=20)[18], 3)
                    if len(latencies) > 1
                    else None,
                    "heartbeat_publication_ms": round(heartbeat_ms, 3),
                    "heartbeat_decisions_validated": 0,
                    "one_decision_publication_ms": round(decision_ms, 3),
                    "changed_decisions_validated": validations,
                }
            )
        )


if __name__ == "__main__":
    main()
