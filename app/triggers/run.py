import argparse
import json
from datetime import date, timedelta

from app.events.store import parse_watchlist
from app.paper.context import position_tickers
from app.prices.cache import refresh_ticker
from app.storage.database import connect
from app.triggers.evaluate import evaluate_triggers
from app.triggers.store import mark_triggers


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.triggers.run")
    parser.add_argument("command", choices=("evaluate", "list", "mark"))
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--watchlist", default="docs/watchlist.md")
    parser.add_argument("--date")
    parser.add_argument("--status", default="pending")
    parser.add_argument("--ids")
    args = parser.parse_args()
    conn = connect(args.db)
    if args.command == "evaluate":
        refresh_through = date.fromisoformat(args.date) if args.date else date.today()
        tickers = sorted(set(parse_watchlist(args.watchlist)) | set(position_tickers(conn)))
        for ticker in tickers:
            refresh_ticker(
                conn,
                ticker,
                refresh_through - timedelta(days=35),
                refresh_through + timedelta(days=1),
            )
        latest = conn.execute("SELECT MAX(bar_date) FROM daily_prices").fetchone()[0]
        evaluation_date = (
            date.fromisoformat(args.date)
            if args.date
            else date.fromisoformat(latest)
            if latest is not None
            else date.today()
        )
        counts = evaluate_triggers(conn, tickers, evaluation_date)
        print(" ".join(f"{key}={value}" for key, value in counts.items()))
    elif args.command == "list":
        rows = conn.execute(
            """
            SELECT trigger_id, fired_at, details_json FROM trigger_events
            WHERE status = ? ORDER BY fired_at, trigger_id
            """,
            (args.status,),
        ).fetchall()
        for item, fired_at, details_json in rows:
            print(f"{fired_at} {item} {json.loads(details_json)}")
    else:
        if not args.ids:
            raise ValueError("mark requires --ids")
        print(f"marked={mark_triggers(conn, args.ids.split(','), args.status)}")


if __name__ == "__main__":
    main()
