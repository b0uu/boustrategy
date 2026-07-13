import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Curated accounts come from `docs/x_manual/README.md`, which is maintainer-owned
# content, not instructions. Only handle text and reason text are ever extracted;
# nothing in that file is ever executed or otherwise acted upon.
_LINE_PATTERN = re.compile(r"^-\s*@(\w+)(.*)$")
_CATEGORIES_PATTERN = re.compile(r"\[(.*?)\]")


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str
    user_id: str | None = None
    categories: list[str] = Field(default_factory=list)
    included_reason: str = ""
    tier: str = "core"
    status: str = "active"

    @field_validator("handle")
    @classmethod
    def normalize_handle(cls, value: str) -> str:
        return value.strip().lstrip("@").lower()


def upsert_account(conn: sqlite3.Connection, account: Account) -> bool:
    row = conn.execute(
        """
        SELECT user_id, categories, included_reason, tier, status
        FROM x_accounts WHERE handle = ?
        """,
        (account.handle,),
    ).fetchone()

    new_values = {
        "user_id": account.user_id,
        "categories": account.categories,
        "included_reason": account.included_reason,
        "tier": account.tier,
        "status": account.status,
    }

    if row is None:
        conn.execute(
            """
            INSERT INTO x_accounts (handle, user_id, categories, included_reason, tier, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account.handle,
                account.user_id,
                json.dumps(account.categories),
                account.included_reason,
                account.tier,
                account.status,
            ),
        )
        _log_event(conn, account.handle, "added")
        conn.commit()
        return True

    existing_values = {
        "user_id": row[0],
        "categories": json.loads(row[1]),
        "included_reason": row[2],
        "tier": row[3],
        "status": row[4],
    }
    if existing_values == new_values:
        return False

    conn.execute(
        """
        UPDATE x_accounts
        SET user_id = ?, categories = ?, included_reason = ?, tier = ?, status = ?
        WHERE handle = ?
        """,
        (
            account.user_id,
            json.dumps(account.categories),
            account.included_reason,
            account.tier,
            account.status,
            account.handle,
        ),
    )
    for field in ("user_id", "categories", "included_reason", "tier", "status"):
        if existing_values[field] != new_values[field]:
            _log_event(
                conn, account.handle, f"{field}: {existing_values[field]} -> {new_values[field]}"
            )
    conn.commit()
    return True


def _log_event(conn: sqlite3.Connection, handle: str, change: str) -> None:
    conn.execute(
        "INSERT INTO x_account_events (handle, change, occurred_at) VALUES (?, ?, ?)",
        (handle, change, datetime.now(UTC).isoformat()),
    )


def list_active_accounts(conn: sqlite3.Connection, tier: str | None = None) -> list[Account]:
    query = (
        "SELECT handle, user_id, categories, included_reason, tier, status "
        "FROM x_accounts WHERE status = 'active'"
    )
    parameters: list[str] = []
    if tier is not None:
        query += " AND tier = ?"
        parameters.append(tier)

    rows = conn.execute(query, parameters).fetchall()
    return [
        Account(
            handle=row[0],
            user_id=row[1],
            categories=json.loads(row[2]),
            included_reason=row[3],
            tier=row[4],
            status=row[5],
        )
        for row in rows
    ]


def _parse_line(line: str) -> tuple[str, list[str], str] | None:
    match = _LINE_PATTERN.match(line)
    if match is None:
        return None
    handle = match.group(1)
    rest = match.group(2)

    categories: list[str] = []
    reason = rest
    categories_match = _CATEGORIES_PATTERN.search(rest)
    if categories_match is not None:
        categories = [c.strip() for c in categories_match.group(1).split(",") if c.strip()]
        reason = rest[categories_match.end() :]

    reason = reason.strip().lstrip("-").strip()
    return handle, categories, reason


def seed_from_manual_readme(conn: sqlite3.Connection, path: str | Path) -> int:
    text = Path(path).read_text(encoding="utf-8")
    changed = 0
    for line in text.splitlines():
        parsed = _parse_line(line)
        if parsed is None:
            continue
        handle, categories, reason = parsed
        account = Account(handle=handle, categories=categories, included_reason=reason)
        if upsert_account(conn, account):
            changed += 1
    return changed
