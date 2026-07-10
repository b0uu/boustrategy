import pytest

from app.orders.create_order_intent import create_order_intent
from app.policy.decision_policy import PolicyResult
from app.storage.database import connect
from app.storage.records import (
    get_decision_record,
    get_order_intent,
    save_decision_record,
    save_order_intent,
)
from tests.fixtures.decision_records import decision_record_with, valid_decision_record


def test_decision_record_round_trip():
    conn = connect(":memory:")
    record = valid_decision_record()

    save_decision_record(conn, record)
    loaded = get_decision_record(conn, record.decision_id)

    assert loaded == record


def test_saving_identical_record_twice_is_noop():
    conn = connect(":memory:")
    record = valid_decision_record()

    first = save_decision_record(conn, record)
    second = save_decision_record(conn, record)
    row_count = conn.execute("SELECT COUNT(*) FROM decision_records").fetchone()[0]

    assert first is True
    assert second is False
    assert row_count == 1


def test_saving_conflicting_record_raises():
    conn = connect(":memory:")
    record = valid_decision_record()
    conflicting = decision_record_with(internal_notes="changed")
    save_decision_record(conn, record)

    with pytest.raises(ValueError):
        save_decision_record(conn, conflicting)


def test_get_missing_record_returns_none():
    conn = connect(":memory:")

    loaded = get_decision_record(conn, "missing")

    assert loaded is None


def test_order_intent_round_trip():
    conn = connect(":memory:")
    intent = create_order_intent(valid_decision_record(), PolicyResult(approved=True))

    save_order_intent(conn, intent)
    loaded = get_order_intent(conn, intent.order_intent_id)

    assert loaded == intent


def test_second_intent_for_same_decision_is_rejected():
    conn = connect(":memory:")
    first = create_order_intent(valid_decision_record(), PolicyResult(approved=True))
    second = first.model_copy(update={"order_intent_id": "oi_different"})
    save_order_intent(conn, first)

    with pytest.raises(ValueError):
        save_order_intent(conn, second)


def test_database_file_created_on_connect(tmp_path):
    db_path = tmp_path / "sub" / "x.db"

    conn = connect(db_path)
    conn.close()

    assert db_path.exists()
