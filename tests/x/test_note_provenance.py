from datetime import date
from pathlib import Path

from app.storage.database import connect
from app.x.pipeline import stamp_note_provenance, store_note


def test_the_wrapper_stamps_the_model_that_wrote_a_digest_note(tmp_path: Path) -> None:
    conn = connect(tmp_path / "boustrategy.db")
    store_note(conn, date(2026, 9, 23), "morning", "codex-gpt56luna-rubric2", "Synthesis.")

    stamped = stamp_note_provenance(conn, date(2026, 9, 23), "morning", "gpt-5.6-luna", "low")
    missing = stamp_note_provenance(conn, date(2026, 9, 23), "midday", "gpt-5.6-luna", "low")

    assert (stamped, missing) == (True, False)
    assert conn.execute(
        "SELECT model, reasoning_effort FROM x_digest_notes WHERE slot = 'morning'"
    ).fetchone() == ("gpt-5.6-luna", "low")
    conn.close()
