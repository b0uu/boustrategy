import argparse
from datetime import datetime

from app.events.fetch import FOMC_COVERAGE_END
from app.events.store import parse_watchlist, refresh_earnings, sync_fomc, upcoming_events
from app.paper.context import position_tickers
from app.storage.database import connect
from app.x.calendar import NEW_YORK


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.events.run")
    parser.add_argument("command", choices=("refresh", "upcoming"))
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--watchlist", default="docs/watchlist.md")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        if args.command == "refresh":
            tickers = sorted(set(parse_watchlist(args.watchlist)) | set(position_tickers(conn)))
            if not tickers:
                print("Watchlist empty. Approve tickers in docs/watchlist.md.")
            for ticker in tickers:
                print(f"{ticker}: {refresh_earnings(conn, ticker)} earnings dates")
            print(f"FOMC: {sync_fomc(conn, FOMC_COVERAGE_END)} meeting days")
        else:
            for event_date, event_type, ticker, label in upcoming_events(
                conn, datetime.now(NEW_YORK).date(), args.days
            ):
                subject = ticker or "FOMC"
                print(f"{event_date} {event_type} {subject} {label}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
