import argparse
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from app.storage.database import connect
from app.x.accounts import list_active_accounts, seed_from_manual_readme, upsert_account
from app.x.client import FetchResult, fetch_user_posts, resolve_user_ids
from app.x.posts import (
    MAX_MONTHLY_POST_READS,
    insert_new_posts,
    mark_reviewed,
    reads_remaining,
    record_post_reads,
    unreviewed_posts,
)
from app.x.signals import CapturedSignal, ClaimType, Horizon, ScrutinyVerdict, Stance, save_signal

DEFAULT_DB_PATH = "data/boustrategy.db"
MANUAL_README_PATH = "docs/x_manual/README.md"
_BUDGET_FLOOR = 100


def _cmd_seed(conn: sqlite3.Connection) -> None:
    count = seed_from_manual_readme(conn, MANUAL_README_PATH)
    print(f"seed: {count} accounts added or changed")


def _cmd_status(conn: sqlite3.Connection) -> None:
    active = len(list_active_accounts(conn))
    unreviewed = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status = 'unreviewed'"
    ).fetchone()[0]
    captured = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status = 'captured'"
    ).fetchone()[0]
    skipped = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status = 'skipped'"
    ).fetchone()[0]
    remaining = reads_remaining(conn)
    used = MAX_MONTHLY_POST_READS - remaining
    print(f"active accounts: {active}")
    print(f"posts: unreviewed={unreviewed} captured={captured} skipped={skipped}")
    print(f"reads this month: used={used} remaining={remaining}")


def _cmd_fetch(
    conn: sqlite3.Connection,
    resolve_ids: Callable[[list[str]], dict[str, str]] = resolve_user_ids,
    fetch_posts: Callable[[str, str, str | None], FetchResult] = fetch_user_posts,
) -> None:
    accounts = list_active_accounts(conn, tier="core")

    missing_handles = [account.handle for account in accounts if account.user_id is None]
    if missing_handles:
        resolved = resolve_ids(missing_handles)
        for account in accounts:
            if account.user_id is None and account.handle in resolved:
                account.user_id = resolved[account.handle]
                upsert_account(conn, account)

    for account in accounts:
        if account.user_id is None:
            print(f"{account.handle}: no user_id resolved, skipping")
            continue

        remaining = reads_remaining(conn)
        if remaining <= _BUDGET_FLOOR:
            print(f"budget guard: only {remaining} reads remaining this month, stopping fetch")
            return

        # post_id is TEXT with varying length; CAST forces numeric MAX so a short
        # old ID (e.g. '99999999999') never lexicographically beats a 19-digit one.
        since_row = conn.execute(
            "SELECT MAX(CAST(post_id AS INTEGER)) FROM x_posts WHERE handle = ?",
            (account.handle,),
        ).fetchone()
        max_post_id = since_row[0] if since_row is not None else None
        since_id = str(max_post_id) if max_post_id is not None else None

        result = fetch_posts(account.user_id, account.handle, since_id)
        new_count = insert_new_posts(conn, result.posts)
        record_post_reads(conn, result.billed_reads)
        print(f"{account.handle}: {new_count} new posts, {reads_remaining(conn)} reads remaining")


def _cmd_review(conn: sqlite3.Connection) -> None:
    for post in unreviewed_posts(conn):
        print(f"\n@{post.handle} ({post.posted_at.isoformat()})")
        print(post.text)
        choice = input("[c]apture / [s]kip / [q]uit: ").strip().lower()
        if choice == "q":
            break
        if choice == "s":
            mark_reviewed(conn, post.post_id, "skipped")
            continue
        if choice != "c":
            continue

        primary_theme_id = input("primary_theme_id: ").strip()
        tickers = [t.strip() for t in input("tickers (comma separated): ").split(",") if t.strip()]
        claim = input("claim: ").strip()
        claim_type = ClaimType(input(f"claim_type {[e.value for e in ClaimType]}: ").strip())
        stance = Stance(input(f"stance {[e.value for e in Stance]}: ").strip())
        horizon = Horizon(input(f"horizon {[e.value for e in Horizon]}: ").strip())
        scrutiny_verdict = ScrutinyVerdict(
            input(f"scrutiny_verdict {[e.value for e in ScrutinyVerdict]}: ").strip()
        )
        why_it_matters = input("why_it_matters: ").strip()

        signal = CapturedSignal(
            entry_id=f"xs_{post.post_id}",
            post_id=post.post_id,
            captured_at=datetime.now(UTC),
            post_url=post.url,
            handle=post.handle,
            posted_at=post.posted_at,
            primary_theme_id=primary_theme_id,
            tickers=tickers,
            claim=claim,
            claim_type=claim_type,
            stance=stance,
            horizon=horizon,
            scrutiny_verdict=scrutiny_verdict,
            why_it_matters=why_it_matters,
        )
        save_signal(conn, signal)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.x.run")
    parser.add_argument("command", choices=["seed", "fetch", "review", "status"])
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    conn = connect(args.db)
    handlers: dict[str, Callable[[sqlite3.Connection], None]] = {
        "seed": _cmd_seed,
        "fetch": _cmd_fetch,
        "review": _cmd_review,
        "status": _cmd_status,
    }
    handlers[args.command](conn)


if __name__ == "__main__":
    main()
