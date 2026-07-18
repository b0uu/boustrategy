import argparse
from datetime import date

from app.paper.broker import STARTING_CASH, cash_balance, settle
from app.paper.context import _latest_close
from app.storage.database import connect


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.paper.run")
    parser.add_argument("command", choices=("settle", "positions", "equity"))
    parser.add_argument("--db", default="data/boustrategy.db")
    args = parser.parse_args()
    conn = connect(args.db)
    if args.command == "settle":
        fills, awaiting = settle(conn)
        print(f"fills={fills} awaiting={awaiting} skips=0")
        return
    today = date.today()
    rows = conn.execute(
        "SELECT ticker, shares, avg_cost, primary_theme_id FROM paper_positions ORDER BY ticker"
    ).fetchall()
    positions_value = 0.0
    for ticker, shares, avg_cost, theme in rows:
        close = _latest_close(conn, ticker, today)
        value = shares * close
        positions_value += value
        if args.command == "positions":
            equity = cash_balance(conn, today) + sum(
                item[1] * _latest_close(conn, item[0], today) for item in rows
            )
            print(
                f"{ticker} shares={shares:.6f} avg_cost={avg_cost:.2f} close={close:.2f} "
                f"value={value:.2f} weight={value / equity:.4f} theme={theme} "
                f"unrealized_pl={(close - avg_cost) * shares:.2f}"
            )
    if args.command == "equity":
        cash = cash_balance(conn, today)
        total = cash + positions_value
        print(
            f"cash={cash:.2f} positions={positions_value:.2f} total={total:.2f} "
            f"vs_start={total - STARTING_CASH:.2f} frictionless=true"
        )


if __name__ == "__main__":
    main()
