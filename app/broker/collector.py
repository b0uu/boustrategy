"""Trusted account and quote collection for the live profile.

A broker session reads Robinhood through the bot's Codex identity and returns one
observation. This module checks the account fingerprint, attaches the theme each
position was opened under, and persists the snapshot through the same storage
boundary the manual CLI uses. Nothing here reviews or places an order.
"""

import argparse
import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.broker.config import get_live_profile, load_live_profiles
from app.broker.session import run_broker_session
from app.schemas.live_execution import (
    BrokerPreflight,
    ExecutionProfile,
    LivePortfolioSnapshot,
    LivePosition,
)
from app.storage.database import connect
from app.storage.records import save_live_portfolio_snapshot

DEFAULT_COLLECTOR_MODEL = "gpt-5.6-luna"
_NEW_YORK = ZoneInfo("America/New_York")
_FINGERPRINT_COMMAND = (
    'python -c "import hashlib,sys; '
    'print(hashlib.sha256(sys.argv[1].strip().encode()).hexdigest()[:16])" <account_number>'
)


class ObservedPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ticker: str = Field(min_length=1, max_length=12)
    market_value: float = Field(ge=0.0)
    quantity: float = Field(ge=0.0)


class AccountObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    broker_account_fingerprint: str = Field(pattern=r"^[a-f0-9]{16}$")
    account_number_last4: str | None = Field(default=None, max_length=4)
    account_equity: float = Field(gt=0.0)
    buying_power: float = Field(ge=0.0)
    positions: list[ObservedPosition] = Field(default_factory=list, max_length=50)
    broker_reported_at: str | None = Field(default=None, max_length=64)


class QuoteObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    broker_account_fingerprint: str = Field(pattern=r"^[a-f0-9]{16}$")
    ticker: str = Field(min_length=1, max_length=12)
    bid: float = Field(gt=0.0)
    ask: float = Field(gt=0.0)
    quote_at: AwareDatetime
    tradable: bool
    fractionable: bool
    regular_market_hours: bool
    account_equity: float = Field(gt=0.0)
    buying_power: float = Field(ge=0.0)
    current_position_value: float = Field(ge=0.0)


def default_codex_home() -> str:
    return os.environ.get("CODEX_HOME") or str(Path.home() / ".codex-boustrategy")


def account_selection(profile: ExecutionProfile) -> str:
    return (
        "The broker grant exposes several accounts, including personal ones. Call get_accounts, "
        "then for each account number compute its fingerprint by running "
        f"{_FINGERPRINT_COMMAND} in the shell. Use only the account whose fingerprint equals "
        f"{profile.broker_account_fingerprint} for every later call. Never print a full account "
        "number. Never call any tool that reviews, places, modifies or cancels an order."
    )


def snapshot_prompt(profile: ExecutionProfile) -> str:
    return (
        "You are a read-only account collector for an autonomous investment harness. "
        + account_selection(profile)
        + " Then call get_portfolio and get_equity_positions for that account. Report "
        "account_equity as the total account value including cash and positions; if the "
        "portfolio tool reports equity 0 while cash or buying power is positive, use cash plus "
        "the market value of positions. Report buying_power as cash available to buy. List every "
        "open equity position with its ticker, current market value in dollars and share "
        "quantity. Put the last four characters of the account number in account_number_last4 "
        "and the broker's own timestamp, if any, in broker_reported_at. Return only the JSON "
        "object required by the schema."
    )


def preflight_prompt(profile: ExecutionProfile, ticker: str) -> str:
    return (
        "You are a read-only quote collector for an autonomous investment harness. "
        + account_selection(profile)
        + f" Then, for the symbol {ticker}: call get_equity_quotes for the current bid, ask and "
        "the broker's quote timestamp; call get_equity_tradability for that account to learn "
        "whether the symbol is tradable and whether fractional shares are allowed; call "
        "get_portfolio for account_equity and buying_power; call get_equity_positions and report "
        f"current_position_value as the market value held in {ticker}, or 0 if none. Set "
        "regular_market_hours to true only if the current New York time is inside the regular "
        "09:30 to 16:00 session on a trading day. quote_at must be an ISO 8601 timestamp with a "
        "timezone offset. Return only the JSON object required by the schema."
    )


def theme_for_ticker(conn: sqlite3.Connection, ticker: str) -> str:
    row = conn.execute(
        "SELECT record_json FROM decision_records WHERE ticker=? ORDER BY created_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if row is None:
        return "unclassified"
    return str(json.loads(row[0]).get("primary_theme_id") or "unclassified")


def collect_snapshot(
    conn: sqlite3.Connection,
    profile: ExecutionProfile,
    *,
    model: str = DEFAULT_COLLECTOR_MODEL,
    codex_home: str | Path | None = None,
    now: datetime | None = None,
    session: Callable[..., Any] = run_broker_session,
    log_dir: Path | None = None,
) -> LivePortfolioSnapshot:
    captured = now or datetime.now(UTC)
    stamp = captured.strftime("%Y%m%dT%H%M%S%fZ")
    observed = session(
        snapshot_prompt(profile),
        schema=AccountObservation,
        model=model,
        codex_home=codex_home or default_codex_home(),
        log_path=log_dir / f"snapshot-{profile.execution_profile_id}-{stamp}.log"
        if log_dir
        else None,
    )
    if observed.broker_account_fingerprint != profile.broker_account_fingerprint:
        raise ValueError("collector_account_mismatch")
    snapshot = LivePortfolioSnapshot(
        portfolio_snapshot_id=f"snap_{profile.execution_profile_id}_{stamp}",
        execution_profile_id=profile.execution_profile_id,
        broker_account_fingerprint=profile.broker_account_fingerprint,
        captured_at=captured,
        account_equity=observed.account_equity,
        buying_power=observed.buying_power,
        positions=[
            LivePosition(
                ticker=position.ticker,
                market_value=position.market_value,
                primary_theme_id=theme_for_ticker(conn, position.ticker),
            )
            for position in observed.positions
            if position.market_value > 0
        ],
    )
    save_live_portfolio_snapshot(conn, snapshot, profile)
    return snapshot


def collect_preflight(
    profile: ExecutionProfile,
    ticker: str,
    *,
    model: str = DEFAULT_COLLECTOR_MODEL,
    codex_home: str | Path | None = None,
    session: Callable[..., Any] = run_broker_session,
    log_dir: Path | None = None,
) -> BrokerPreflight:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    observed = session(
        preflight_prompt(profile, ticker),
        schema=QuoteObservation,
        model=model,
        codex_home=codex_home or default_codex_home(),
        log_path=log_dir / f"preflight-{ticker}-{stamp}.log" if log_dir else None,
    )
    if observed.broker_account_fingerprint != profile.broker_account_fingerprint:
        raise ValueError("collector_account_mismatch")
    if observed.ticker.upper() != ticker.upper():
        raise ValueError("collector_ticker_mismatch")
    return BrokerPreflight(
        execution_profile_id=profile.execution_profile_id,
        broker_account_fingerprint=profile.broker_account_fingerprint,
        account_equity=observed.account_equity,
        buying_power=observed.buying_power,
        ticker=ticker.upper(),
        current_position_value=observed.current_position_value,
        bid=observed.bid,
        ask=observed.ask,
        quote_at=observed.quote_at,
        tradable=observed.tradable,
        fractionable=observed.fractionable,
        regular_market_hours=observed.regular_market_hours,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.broker.collector")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--profiles", default="ops/live.local.json")
    parser.add_argument("--profile", default="codex")
    parser.add_argument("--model", default=DEFAULT_COLLECTOR_MODEL)
    parser.add_argument("--codex-home", default=default_codex_home())
    parser.add_argument("--logs", default="data/logs/broker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("snapshot")
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--ticker", required=True)
    prepare = subparsers.add_parser("prepare-live")
    prepare.add_argument("--slot", required=True)
    prepare.add_argument("--model-label", required=True)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--date")
    prepare.add_argument("--digest-dir", default="data/digests")
    args = parser.parse_args()

    profile = get_live_profile(load_live_profiles(args.profiles), args.profile)
    if not profile.enabled:
        raise ValueError(f"execution profile {profile.execution_profile_id} is disabled")
    log_dir = Path(args.logs)
    if args.command == "preflight":
        result = collect_preflight(
            profile, args.ticker, model=args.model, codex_home=args.codex_home, log_dir=log_dir
        )
        print(result.model_dump_json())
        return
    with closing(connect(args.db)) as conn:
        snapshot = collect_snapshot(
            conn, profile, model=args.model, codex_home=args.codex_home, log_dir=log_dir
        )
        summary: dict[str, Any] = {
            "portfolio_snapshot_id": snapshot.portfolio_snapshot_id,
            "captured_at": snapshot.captured_at.isoformat(),
            "account_equity": snapshot.account_equity,
            "buying_power": snapshot.buying_power,
            "positions": len(snapshot.positions),
        }
        if args.command == "prepare-live":
            from app.reason.run import prepare_live_runs

            on_date = date.fromisoformat(args.date) if args.date else datetime.now(_NEW_YORK).date()
            runs = prepare_live_runs(
                conn,
                on_date,
                args.slot,
                args.out,
                [(profile.execution_profile_id, args.model_label, snapshot.portfolio_snapshot_id)],
                digest_dir=args.digest_dir,
            )
            summary["reasoning_runs"] = [run.reasoning_run_id for run in runs]
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
