import argparse
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.prices.cache import get_daily_prices, refresh_ticker
from app.regime.rules import RegimeScore, publish_regime, score_regime
from app.schemas.decision_record import RegimeState
from app.storage.database import connect


def _components_json(score: RegimeScore) -> str:
    return json.dumps(
        {
            name: {"value": component.value, "points": component.points}
            for name, component in score.components.items()
        },
        sort_keys=True,
    )


def save_snapshot(conn: sqlite3.Connection, snapshot_date: date, score: RegimeScore) -> RegimeState:
    rows = conn.execute(
        "SELECT regime, raw_regime FROM regime_snapshots ORDER BY snapshot_date"
    ).fetchall()
    previous = RegimeState(rows[-1][0]) if rows else None
    raw_history = [RegimeState(row[1]) for row in rows[-1:]] + [score.raw_regime]
    published = publish_regime(previous, raw_history)
    components_json = _components_json(score)
    existing = conn.execute(
        """
        SELECT regime, raw_regime, score, components_json FROM regime_snapshots
        WHERE snapshot_date = ?
        """,
        (snapshot_date.isoformat(),),
    ).fetchone()
    values = (published.value, score.raw_regime.value, score.score, components_json)
    if existing is not None:
        if existing == values:
            return published
        raise ValueError(f"snapshot {snapshot_date} already exists with different rules output")
    conn.execute(
        """
        INSERT INTO regime_snapshots
            (snapshot_date, regime, raw_regime, score, components_json, computed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (snapshot_date.isoformat(), *values, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    return published


def score_date(conn: sqlite3.Connection, target: date) -> tuple[RegimeState, RegimeScore]:
    spy = get_daily_prices(conn, "SPY", end=target)
    qqq = get_daily_prices(conn, "QQQ", end=target)
    score = score_regime(spy, qqq)
    return save_snapshot(conn, target, score), score


def render_backtest(conn: sqlite3.Connection, start: date, end: date) -> str:
    spy = get_daily_prices(conn, "SPY", end=end)
    qqq = get_daily_prices(conn, "QQQ", end=end)
    spy_by_date = {bar.bar_date: index for index, bar in enumerate(spy)}
    qqq_by_date = {bar.bar_date: index for index, bar in enumerate(qqq)}
    dates = sorted(set(spy_by_date) & set(qqq_by_date))
    rows: list[tuple[date, RegimeState, RegimeScore]] = []
    published: RegimeState | None = None
    raw_history: list[RegimeState] = []
    for current in dates:
        if current < start or current > end:
            continue
        spy_slice = spy[: spy_by_date[current] + 1]
        qqq_slice = qqq[: qqq_by_date[current] + 1]
        if len(spy_slice) < 504 or len(qqq_slice) < 504:
            continue
        score = score_regime(spy_slice, qqq_slice)
        raw_history.append(score.raw_regime)
        published = publish_regime(published, raw_history)
        rows.append((current, published, score))
    if not rows:
        raise ValueError("backtest range has no dates with 504 sessions of shared history")
    state_counts = {state: sum(row[1] == state for row in rows) for state in RegimeState}
    lines = [
        "# Regime scorer v0 backtest (REVIEW-REQUIRED)",
        "",
        f"Range: {start} through {end}",
        "",
        "## Days per published state",
        "",
    ]
    lines += [f"- {state.value}: {state_counts[state]}" for state in RegimeState]
    lines += ["", "## State changes", ""]
    previous: RegimeState | None = None
    for current, state, score in rows:
        if state != previous:
            lines.append(
                f"- {current}: {state.value} (score {score.score}) `{_components_json(score)}`"
            )
            previous = state
    lines += [
        "",
        "## Score time series",
        "",
        "| Date | Published | Raw | Score |",
        "|---|---|---|---:|",
    ]
    lines += [
        f"| {current} | {state.value} | {score.raw_regime.value} | {score.score} |"
        for current, state, score in rows
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.regime.run")
    parser.add_argument("command", choices=("score", "backtest"))
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--date")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--out")
    args = parser.parse_args()
    conn = connect(args.db)
    if args.command == "score":
        target = date.fromisoformat(args.date) if args.date else date.today()
        for ticker in ("SPY", "QQQ"):
            refresh_ticker(conn, ticker, target - timedelta(days=760), target + timedelta(days=1))
        published, score = score_date(conn, target)
        print(f"regime={published.value} raw={score.raw_regime.value} score={score.score}")
        print(_components_json(score))
    else:
        if not args.start or not args.end or not args.out:
            raise ValueError("backtest requires --start, --end, and --out")
        text = render_backtest(conn, date.fromisoformat(args.start), date.fromisoformat(args.end))
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
