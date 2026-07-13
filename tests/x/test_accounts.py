import re

from app.storage.database import connect
from app.x.accounts import Account, list_active_accounts, seed_from_manual_readme, upsert_account

README_PATH = "docs/x_manual/README.md"
_HANDLE_PATTERN = re.compile(r"^-\s*@(\w+)")


def test_seed_from_manual_readme_imports_every_handle_and_is_idempotent():
    conn = connect(":memory:")

    with open(README_PATH, encoding="utf-8") as handle_file:
        lines = handle_file.read().splitlines()
    expected_handles = {
        match.group(1).lower() for line in lines if (match := _HANDLE_PATTERN.match(line))
    }

    first_run = seed_from_manual_readme(conn, README_PATH)
    accounts = list_active_accounts(conn)

    assert first_run == len(accounts)
    assert first_run > 0
    assert {account.handle for account in accounts} == expected_handles

    second_run = seed_from_manual_readme(conn, README_PATH)
    assert second_run == 0


def test_upsert_account_logs_event_on_insert_and_change_but_not_on_repeat():
    conn = connect(":memory:")
    account = Account(handle="testhandle", categories=["news"], included_reason="test")

    changed = upsert_account(conn, account)
    events_after_insert = conn.execute(
        "SELECT COUNT(*) FROM x_account_events WHERE handle = ?", ("testhandle",)
    ).fetchone()[0]

    assert changed is True
    assert events_after_insert == 1

    same_again = upsert_account(conn, account)
    events_after_repeat = conn.execute(
        "SELECT COUNT(*) FROM x_account_events WHERE handle = ?", ("testhandle",)
    ).fetchone()[0]

    assert same_again is False
    assert events_after_repeat == 1

    changed_account = Account(
        handle="testhandle", categories=["news"], included_reason="test", tier="scan"
    )
    changed_again = upsert_account(conn, changed_account)
    events_after_change = conn.execute(
        "SELECT COUNT(*) FROM x_account_events WHERE handle = ?", ("testhandle",)
    ).fetchone()[0]

    assert changed_again is True
    assert events_after_change == 2


def test_handle_normalization_treats_variants_as_the_same_account():
    conn = connect(":memory:")

    first = upsert_account(conn, Account(handle="@JuKan05 "))
    second = upsert_account(conn, Account(handle="jukan05"))

    assert first is True
    assert second is False
    assert len(list_active_accounts(conn)) == 1
