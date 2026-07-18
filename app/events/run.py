import argparse
from datetime import date

from app.events.fetch import FOMC_COVERAGE_END
from app.events.store import parse_watchlist, refresh_earnings, sync_fomc, upcoming_events
from app.storage.database import connect


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.events.run")
    parser.add_argument("command", choices=("refresh", "upcoming"))
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--watchlist", default="docs/watchlist.md")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    conn = connect(args.db)
    if args.command == "refresh":
        tickers = parse_watchlist(args.watchlist)
        if not tickers:
            print("watchlist empty â€” approve tickers in docs/watchlist.md")
        for ticker in tickers:
            print(f"{ticker}: {refresh_earnings(conn, ticker)} earnings dates")
        print(f"FOMC: {sync_fomc(conn, FOMC_COVERAGE_END)} meeting days")
    else:
        for event_date, event_type, ticker, label in upcoming_events(conn, date.today(), args.days):
            subject = ticker or "FOMC"
            print(f"{event_date} {event_type} {subject} {label}")


if __name__ == "__main__":
    main()
