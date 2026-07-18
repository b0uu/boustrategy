import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.x.signals import ClaimType, Horizon, Stance


class NewsletterClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    claim_type: ClaimType
    stance: Stance
    horizon: Horizon
    tickers: list[str] = Field(default_factory=list)
    primary_theme_id: str = ""
    why_it_matters: str = ""
    annotated_by: str = Field(min_length=1)


def _source_title(name: str) -> tuple[str, str]:
    stem = Path(name).stem
    if "--" in stem:
        source, title = stem.split("--", 1)
    else:
        source, title = "unknown", stem
        print(f"warning: {name} has no source--title separator; using unknown")
    return source, title


def _identity(path: Path) -> tuple[str, str, str]:
    doc_id = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    source, title = _source_title(path.name)
    return doc_id, source, title


def _insert_doc(conn: sqlite3.Connection, archive_path: Path, source: str, title: str) -> bool:
    doc_id = hashlib.sha256(archive_path.read_bytes()).hexdigest()[:16]
    existing = conn.execute("SELECT 1 FROM newsletter_docs WHERE doc_id = ?", (doc_id,)).fetchone()
    if existing is not None:
        return False
    status = "parsed" if archive_path.suffix.lower() in (".md", ".txt") else "unparsed"
    conn.execute(
        """
        INSERT INTO newsletter_docs
            (doc_id, source, title, received_at, archive_path, parse_status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (doc_id, source, title, datetime.now(UTC).isoformat(), str(archive_path), status),
    )
    conn.commit()
    return True


def ingest(conn: sqlite3.Connection, root: str | Path) -> tuple[int, int]:
    base = Path(root)
    inbox = base / "inbox"
    archive = base / "archive"
    inbox.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    inserted = 0
    duplicates = 0

    for archived in sorted(path for path in archive.glob("*/*") if path.is_file()):
        doc_id, _, original = archived.name.partition("-")
        if len(doc_id) != 16 or not original:
            continue
        source, title = _source_title(original)
        source = archived.parent.name
        if _insert_doc(conn, archived, source, title):
            inserted += 1

    for path in sorted(item for item in inbox.iterdir() if item.is_file()):
        doc_id, source, title = _identity(path)
        existing = conn.execute(
            "SELECT archive_path FROM newsletter_docs WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if existing is not None:
            path.unlink()
            duplicates += 1
            continue
        destination_dir = archive / source
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{doc_id}-{path.name}"
        if not destination.exists():
            path.replace(destination)
        if _insert_doc(conn, destination, source, title):
            inserted += 1
    return inserted, duplicates


def annotate(conn: sqlite3.Connection, doc_id: str, claims_path: str | Path) -> int:
    if conn.execute("SELECT 1 FROM newsletter_docs WHERE doc_id = ?", (doc_id,)).fetchone() is None:
        raise ValueError(f"unknown newsletter doc_id {doc_id!r}")
    claims = [
        NewsletterClaim.model_validate_json(line)
        for line in Path(claims_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    annotated_at = datetime.now(UTC).isoformat()
    inserted = 0
    for index, claim in enumerate(claims, 1):
        claim_id = f"nl_{doc_id}_{index}"
        values = (
            doc_id,
            claim.claim,
            claim.claim_type.value,
            claim.stance.value,
            claim.horizon.value,
            json.dumps(claim.tickers),
            claim.primary_theme_id,
            claim.why_it_matters,
            claim.annotated_by,
        )
        existing = conn.execute(
            """
            SELECT doc_id, claim, claim_type, stance, horizon, tickers,
                   primary_theme_id, why_it_matters, annotated_by
            FROM newsletter_claims WHERE claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        if existing is not None:
            if existing != values:
                raise ValueError(f"claim {claim_id} already exists with different content")
            continue
        conn.execute(
            """
            INSERT INTO newsletter_claims
                (claim_id, doc_id, claim, claim_type, stance, horizon, tickers,
                 primary_theme_id, why_it_matters, annotated_by, annotated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (claim_id, *values, annotated_at),
        )
        inserted += 1
    conn.commit()
    return inserted


def list_docs(conn: sqlite3.Connection, source: str | None = None) -> list[tuple[object, ...]]:
    query = (
        "SELECT d.doc_id, d.source, d.title, d.parse_status, COUNT(c.claim_id) "
        "FROM newsletter_docs d LEFT JOIN newsletter_claims c ON c.doc_id = d.doc_id"
    )
    parameters: tuple[str, ...] = ()
    if source is not None:
        query += " WHERE d.source = ?"
        parameters = (source,)
    query += " GROUP BY d.doc_id ORDER BY d.received_at DESC"
    return conn.execute(query, parameters).fetchall()
