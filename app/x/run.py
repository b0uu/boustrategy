import argparse
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.storage.database import connect
from app.x.accounts import list_active_accounts, seed_from_manual_readme, upsert_account
from app.x.calendar import slot_should_run
from app.x.client import (
    FetchResult,
    UsageResult,
    fetch_post_usage,
    fetch_posts_by_ids,
    fetch_user_posts,
    resolve_user_ids,
)
from app.x.pipeline import cycle, render_digest, render_weekly, route_predictions, store_note
from app.x.posts import (
    MAX_MONTHLY_POST_READS,
    POST_READ_WARNING_THRESHOLD,
    insert_new_posts,
    mark_reviewed,
    reads_remaining,
    record_post_reads,
    set_post_reads,
    unreviewed_posts,
    update_post_enrichment,
)
from app.x.signals import CapturedSignal, ClaimType, Horizon, ScrutinyVerdict, Stance, save_signal

DEFAULT_DB_PATH = "data/boustrategy.db"
MANUAL_README_PATH = "docs/x_manual/README.md"
_BUDGET_FLOOR = 100
_RECOVERY_WINDOW = timedelta(days=4)


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
    significant = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status = 'significant'"
    ).fetchone()[0]
    remaining = reads_remaining(conn)
    used = MAX_MONTHLY_POST_READS - remaining
    print(f"active accounts: {active}")
    print(
        f"posts: unreviewed={unreviewed} captured={captured} "
        f"significant={significant} skipped={skipped}"
    )
    print(f"reads this month: used={used} remaining={remaining}")
    if used >= POST_READ_WARNING_THRESHOLD:
        print(f"budget warning: {used} Post reads used; monthly cap is {MAX_MONTHLY_POST_READS}")


def _cmd_usage_sync(
    conn: sqlite3.Connection,
    fetch_usage: Callable[[], UsageResult] = fetch_post_usage,
) -> None:
    usage = fetch_usage()
    set_post_reads(conn, usage.post_reads)
    remaining = reads_remaining(conn)
    print(
        f"usage sync: used={usage.post_reads} remaining={remaining} "
        f"x_project_cap={usage.project_cap} reset_day={usage.cap_reset_day}"
    )
    if usage.post_reads >= POST_READ_WARNING_THRESHOLD:
        print(
            f"budget warning: {usage.post_reads} Post reads used; "
            f"monthly cap is {MAX_MONTHLY_POST_READS}"
        )


def _cmd_fetch(
    conn: sqlite3.Connection,
    resolve_ids: Callable[[list[str]], dict[str, str]] = resolve_user_ids,
    fetch_posts: Callable[..., FetchResult] = fetch_user_posts,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    accounts = list_active_accounts(conn)

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
            """
            SELECT MAX(CAST(post_id AS INTEGER)), MAX(posted_at)
            FROM x_posts WHERE handle = ?
            """,
            (account.handle,),
        ).fetchone()
        max_post_id = since_row[0] if since_row is not None else None
        newest_posted_at = (
            datetime.fromisoformat(since_row[1].replace("Z", "+00:00"))
            if since_row is not None and since_row[1] is not None
            else None
        )
        recovery_start = now() - _RECOVERY_WINDOW
        use_since_id = newest_posted_at is not None and newest_posted_at >= recovery_start
        since_id = str(max_post_id) if max_post_id is not None and use_since_id else None
        start_time = None if use_since_id else recovery_start

        checkpoint = conn.execute(
            "SELECT since_id, start_time, next_token FROM x_fetch_checkpoints WHERE handle=?",
            (account.handle,),
        ).fetchone()
        token = None
        if checkpoint:
            since_id, start_text, token = checkpoint
            start_time = datetime.fromisoformat(start_text) if start_text else None
        else:
            conn.execute(
                "INSERT INTO x_fetch_checkpoints VALUES (?, ?, ?, NULL)",
                (account.handle, since_id, start_time.isoformat() if start_time else None),
            )
            conn.commit()
        result = (
            fetch_posts(
                account.user_id, account.handle, since_id, start_time, pagination_token=token
            )
            if token
            else fetch_posts(account.user_id, account.handle, since_id, start_time)
        )
        record_post_reads(conn, result.billed_reads)
        new_count = insert_new_posts(conn, result.posts)
        if result.next_token:
            conn.execute(
                "UPDATE x_fetch_checkpoints SET next_token=? WHERE handle=?",
                (result.next_token, account.handle),
            )
            print(f"{account.handle}: pagination incomplete; continuation saved")
        else:
            conn.execute("DELETE FROM x_fetch_checkpoints WHERE handle=?", (account.handle,))
        conn.commit()
        print(f"{account.handle}: {new_count} new posts, {reads_remaining(conn)} reads remaining")


def _cmd_rehydrate(
    conn: sqlite3.Connection,
    fetch_by_ids: Callable[[list[str]], FetchResult] = fetch_posts_by_ids,
) -> None:
    """Backfill conversation_id/reply_context/media_json for pre-012/013
    unreviewed posts by looking them up by ID (plan 014)."""
    rows = conn.execute(
        """
        SELECT post_id FROM x_posts
        WHERE review_status = 'unreviewed' AND conversation_id = ''
        ORDER BY posted_at ASC
        """
    ).fetchall()
    post_ids = [row[0] for row in rows]

    requested = 0
    returned = 0
    updated = 0
    for start in range(0, len(post_ids), 100):
        batch = post_ids[start : start + 100]

        remaining = reads_remaining(conn)
        if remaining <= len(batch) + _BUDGET_FLOOR:
            print(f"budget guard: only {remaining} reads remaining this month, stopping rehydrate")
            break

        requested += len(batch)
        result = fetch_by_ids(batch)
        record_post_reads(conn, result.billed_reads)
        returned += len(result.posts)

        batch_updated = 0
        for post in result.posts:
            if update_post_enrichment(conn, post):
                batch_updated += 1
        updated += batch_updated

        print(
            f"batch {start // 100 + 1}: {batch_updated} updated, "
            f"{reads_remaining(conn)} reads remaining"
        )

    missing = requested - returned
    remaining = reads_remaining(conn)
    used = MAX_MONTHLY_POST_READS - remaining
    print(f"rehydrate: updated={updated} missing={missing} reads_used={used} remaining={remaining}")


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


def _cmd_verify(conn: sqlite3.Connection, slot: str, run_date: date) -> None:
    if slot_should_run(run_date, slot) is None:
        print(f"{run_date.isoformat()} {slot}: verified calendar no-op")
        return
    run_id = f"{run_date.isoformat()}-{slot}"
    row = conn.execute("SELECT status FROM x_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None or row[0] not in ("routed", "digested"):
        status = "missing" if row is None else row[0]
        raise RuntimeError(f"{run_id} didn't complete; status={status}")
    print(f"{run_id}: verified status={row[0]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.x.run")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "fetch", "review", "status", "usage-sync", "rehydrate"):
        subparsers.add_parser(command)

    cycle_parser = subparsers.add_parser("cycle")
    cycle_parser.add_argument(
        "--slot", choices=("morning", "midday", "close", "weekly"), required=True
    )
    cycle_parser.add_argument("--date", dest="run_date")
    cycle_parser.add_argument("--out")

    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("--run", dest="run_id", required=True)
    route_parser.add_argument("--predictor", required=True)
    route_parser.add_argument("--in", dest="in_path", required=True)

    note_parser = subparsers.add_parser("note")
    note_parser.add_argument("--date", dest="note_date", required=True)
    note_parser.add_argument(
        "--slot", choices=("morning", "midday", "close", "weekly"), required=True
    )
    note_parser.add_argument("--author", required=True)
    note_parser.add_argument("--in", dest="in_path", required=True)

    digest_parser = subparsers.add_parser("digest-render")
    digest_parser.add_argument("--date", dest="digest_date", required=True)
    digest_parser.add_argument("--out")

    weekly_parser = subparsers.add_parser("weekly-render")
    weekly_parser.add_argument("--date", dest="weekly_date", required=True)
    weekly_parser.add_argument("--out")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument(
        "--slot", choices=("morning", "midday", "close", "weekly"), required=True
    )
    verify_parser.add_argument("--date", dest="run_date")

    for command_parser in subparsers.choices.values():
        command_parser.add_argument("--db", default=argparse.SUPPRESS)

    args = parser.parse_args()

    with closing(connect(args.db)) as conn:
        handlers: dict[str, Callable[[sqlite3.Connection], None]] = {
            "seed": _cmd_seed,
            "fetch": _cmd_fetch,
            "review": _cmd_review,
            "status": _cmd_status,
            "usage-sync": _cmd_usage_sync,
            "rehydrate": _cmd_rehydrate,
        }
        if args.command in handlers:
            handlers[args.command](conn)
        elif args.command == "cycle":
            run_date = (
                date.fromisoformat(args.run_date)
                if args.run_date
                else datetime.now(ZoneInfo("America/New_York")).date()
            )
            run_id = f"{run_date.isoformat()}-{args.slot}"
            out = args.out or f"data/x_runs/{run_id}"
            cycle(conn, args.slot, run_date, out, _cmd_fetch)
        elif args.command == "route":
            route_predictions(conn, args.run_id, args.predictor, args.in_path)
        elif args.command == "note":
            synthesis = Path(args.in_path).read_text(encoding="utf-8")
            store_note(conn, date.fromisoformat(args.note_date), args.slot, args.author, synthesis)
            print(f"stored note for {args.note_date}-{args.slot}")
        elif args.command == "digest-render":
            digest_date = date.fromisoformat(args.digest_date)
            out = args.out or f"data/digests/{digest_date.isoformat()}.md"
            render_digest(conn, digest_date, out)
            print(f"rendered {out}")
        elif args.command == "weekly-render":
            weekly_date = date.fromisoformat(args.weekly_date)
            out = args.out or f"data/digests/weekly-{weekly_date.isoformat()}.md"
            render_weekly(conn, weekly_date, out)
            print(f"rendered {out}")
        elif args.command == "verify":
            run_date = (
                date.fromisoformat(args.run_date)
                if args.run_date
                else datetime.now(ZoneInfo("America/New_York")).date()
            )
            _cmd_verify(conn, args.slot, run_date)


if __name__ == "__main__":
    main()
