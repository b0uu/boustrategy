import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.newsletters.store import annotate, ingest, list_docs
from app.storage.database import connect


def _drop(root: Path, name: str, content: bytes = b"private content") -> Path:
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(content)
    return path


def test_ingest_reconciles_archive_after_move_before_insert(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    content = b"private content"
    doc_id = hashlib.sha256(content).hexdigest()[:16]
    archive = root / "archive" / "citrini"
    archive.mkdir(parents=True)
    (archive / f"{doc_id}-citrini--power.md").write_bytes(content)

    result = ingest(conn, root)

    assert result == (1, 0)
    assert conn.execute("SELECT source, title FROM newsletter_docs").fetchone() == (
        "citrini",
        "power",
    )


def test_duplicate_drop_is_removed_and_not_reinserted(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    _drop(root, "semi--chips.txt")
    assert ingest(conn, root) == (1, 0)
    duplicate = _drop(root, "semi--duplicate.txt")

    assert ingest(conn, root) == (0, 1)
    assert not duplicate.exists()
    assert conn.execute("SELECT COUNT(*) FROM newsletter_docs").fetchone()[0] == 1


def test_bad_filename_uses_unknown_and_pdf_is_unparsed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    _drop(root, "lazy.pdf")

    ingest(conn, root)

    assert "warning" in capsys.readouterr().out
    assert conn.execute("SELECT source, title, parse_status FROM newsletter_docs").fetchone() == (
        "unknown",
        "lazy",
        "unparsed",
    )


def test_annotate_validates_enums_is_idempotent_and_lists_counts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    _drop(root, "semi--chips.md")
    ingest(conn, root)
    doc_id = conn.execute("SELECT doc_id FROM newsletter_docs").fetchone()[0]
    path = tmp_path / "claims.jsonl"
    record = {
        "claim": "Demand is rising",
        "claim_type": "fact",
        "stance": "confirmation",
        "horizon": "medium",
        "tickers": ["NVDA"],
        "primary_theme_id": "ai_semiconductors",
        "why_it_matters": "Supports demand",
        "annotated_by": "maintainer",
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    assert annotate(conn, doc_id, path) == 1
    assert annotate(conn, doc_id, path) == 0
    assert list_docs(conn, "semi")[0][-1] == 1
    record["stance"] = "invalid"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        annotate(conn, doc_id, path)
    with pytest.raises(ValueError, match="unknown newsletter"):
        annotate(conn, "missing", path)


def test_changed_claim_with_same_position_crashes(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    _drop(root, "semi--chips.md")
    ingest(conn, root)
    doc_id = conn.execute("SELECT doc_id FROM newsletter_docs").fetchone()[0]
    path = tmp_path / "claims.jsonl"
    record = {
        "claim": "First",
        "claim_type": "interpretation",
        "stance": "idea_source",
        "horizon": "long",
        "annotated_by": "maintainer",
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    annotate(conn, doc_id, path)
    record["claim"] = "Changed"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="different content"):
        annotate(conn, doc_id, path)


def test_newsletter_archive_paths_are_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "data/newsletters/archive/source/private.md"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0


@pytest.mark.parametrize("source", ["..", "CON", "semi."])
def test_unsafe_source_does_not_move_inbox(tmp_path: Path, source: str) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    original = _drop(root, source + "--title.txt")
    with pytest.raises(ValueError, match="source path"):
        ingest(conn, root)
    assert original.read_bytes() == b"private content"
    assert conn.execute("SELECT COUNT(*) FROM newsletter_docs").fetchone()[0] == 0
    conn.close()


def test_missing_duplicate_archive_is_restored_before_inbox_removal(tmp_path: Path) -> None:
    conn = connect(tmp_path / "synthetic.db")
    root = tmp_path / "newsletters"
    _drop(root, "semi--chips.txt")
    ingest(conn, root)
    archive = Path(conn.execute("SELECT archive_path FROM newsletter_docs").fetchone()[0])
    archive.rename(archive.with_suffix(".backup"))
    conn.execute("UPDATE newsletter_docs SET archive_path=?", (str(root / "archive" / "missing"),))
    conn.commit()
    duplicate = _drop(root, "semi--duplicate.txt")
    ingest(conn, root)
    saved = Path(conn.execute("SELECT archive_path FROM newsletter_docs").fetchone()[0])
    assert saved.read_bytes() == b"private content"
    assert not duplicate.exists()
    conn.close()
