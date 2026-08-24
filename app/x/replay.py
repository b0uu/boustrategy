import argparse
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from app.prices.cache import PriceBar, get_daily_prices, refresh_ticker
from app.storage.database import connect

_CASHTAG = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z]{1,5})(?![A-Za-z0-9_])")
_TICKER = re.compile(r"^[A-Z]{1,5}$")
_NEW_YORK = ZoneInfo("America/New_York")
_MARKET_OPEN = time(9, 30)
_BENCHMARK = "QQQ"


@dataclass(frozen=True)
class ReplayCandidate:
    source: str
    post_id: str
    handle: str
    rank: str
    available_at: datetime
    tickers: tuple[str, ...]
    url: str


@dataclass(frozen=True)
class ReplayResult:
    source: str
    post_id: str
    handle: str
    rank: str
    available_at: str
    ticker: str
    entry_date: str
    exit_date: str
    horizon_sessions: int
    return_pct: float
    benchmark_return_pct: float
    excess_return_pct: float
    url: str


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp is not timezone-aware: {value}")
    return parsed


def extract_cashtags(text: str) -> tuple[str, ...]:
    return tuple(sorted({match.upper() for match in _CASHTAG.findall(text)}))


def load_candidates(conn: sqlite3.Connection, evaluated_at: datetime) -> list[ReplayCandidate]:
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")

    candidates: list[ReplayCandidate] = []
    route_rows = conn.execute(
        """
        SELECT p.post_id, p.handle, p.posted_at, p.fetched_at, p.text,
               p.reply_context, p.url, r.rank, r.decided_at
        FROM x_posts AS p
        JOIN x_route_decisions AS r ON r.post_id = p.post_id
        WHERE r.route = 'digest'
        ORDER BY r.decided_at, p.post_id
        """
    ).fetchall()
    for (
        post_id,
        handle,
        posted_at,
        fetched_at,
        text,
        reply_context,
        url,
        rank,
        decided_at,
    ) in route_rows:
        tickers = extract_cashtags(f"{text}\n{reply_context}")
        if not tickers:
            continue
        available_at = max(
            _parse_datetime(posted_at),
            _parse_datetime(fetched_at),
            _parse_datetime(decided_at),
        )
        if available_at <= evaluated_at:
            candidates.append(
                ReplayCandidate(
                    source="route",
                    post_id=post_id,
                    handle=handle,
                    rank=rank,
                    available_at=available_at,
                    tickers=tickers,
                    url=url,
                )
            )

    signal_rows = conn.execute(
        """
        SELECT p.post_id, p.handle, p.posted_at, p.fetched_at, p.url,
               s.signal_json, s.captured_at
        FROM x_posts AS p
        JOIN x_signals AS s ON s.post_id = p.post_id
        ORDER BY s.captured_at, p.post_id
        """
    ).fetchall()
    for post_id, handle, posted_at, fetched_at, url, signal_json, captured_at in signal_rows:
        signal = json.loads(signal_json)
        tickers = tuple(
            sorted(
                {
                    str(ticker).upper()
                    for ticker in signal.get("tickers", [])
                    if _TICKER.fullmatch(str(ticker).upper())
                }
            )
        )
        if not tickers:
            continue
        available_at = max(
            _parse_datetime(posted_at),
            _parse_datetime(fetched_at),
            _parse_datetime(captured_at),
        )
        if available_at <= evaluated_at:
            candidates.append(
                ReplayCandidate(
                    source="capture",
                    post_id=post_id,
                    handle=handle,
                    rank="captured",
                    available_at=available_at,
                    tickers=tickers,
                    url=url,
                )
            )

    return candidates


def _adjusted_open(bar: PriceBar) -> float:
    if bar.adj_close is None or bar.close == 0:
        return bar.open
    return bar.open * bar.adj_close / bar.close


def _adjusted_close(bar: PriceBar) -> float:
    return bar.adj_close if bar.adj_close is not None else bar.close


def _entry_index(bars: list[PriceBar], available_at: datetime) -> int | None:
    local = available_at.astimezone(_NEW_YORK)
    may_use_same_day_open = local.time().replace(tzinfo=None) < _MARKET_OPEN
    for index, bar in enumerate(bars):
        if bar.bar_date > local.date():
            return index
        if bar.bar_date == local.date() and may_use_same_day_open:
            return index
    return None


def evaluate_candidates(
    conn: sqlite3.Connection,
    candidates: list[ReplayCandidate],
    evaluated_at: datetime,
    horizons: tuple[int, ...] = (1, 5, 20),
) -> tuple[list[ReplayResult], list[str]]:
    if not horizons or any(horizon < 1 for horizon in horizons):
        raise ValueError("horizons must contain positive session counts")

    evaluated_date = evaluated_at.astimezone(_NEW_YORK).date()
    benchmark = get_daily_prices(conn, _BENCHMARK, end=evaluated_date)
    benchmark_by_date = {bar.bar_date: bar for bar in benchmark}
    results: list[ReplayResult] = []
    missing: set[str] = set()

    for candidate in candidates:
        for ticker in candidate.tickers:
            bars = get_daily_prices(conn, ticker, end=evaluated_date)
            entry_index = _entry_index(bars, candidate.available_at)
            if entry_index is None:
                missing.add(ticker)
                continue
            entry_bar = bars[entry_index]
            entry_price = _adjusted_open(entry_bar)
            benchmark_entry = benchmark_by_date.get(entry_bar.bar_date)
            if benchmark_entry is None:
                missing.add(_BENCHMARK)
                continue
            benchmark_entry_price = _adjusted_open(benchmark_entry)

            for horizon in horizons:
                exit_index = entry_index + horizon - 1
                if exit_index >= len(bars):
                    continue
                exit_bar = bars[exit_index]
                benchmark_exit = benchmark_by_date.get(exit_bar.bar_date)
                if benchmark_exit is None:
                    missing.add(_BENCHMARK)
                    continue
                ticker_return = _adjusted_close(exit_bar) / entry_price - 1
                benchmark_return = _adjusted_close(benchmark_exit) / benchmark_entry_price - 1
                results.append(
                    ReplayResult(
                        source=candidate.source,
                        post_id=candidate.post_id,
                        handle=candidate.handle,
                        rank=candidate.rank,
                        available_at=candidate.available_at.isoformat(),
                        ticker=ticker,
                        entry_date=entry_bar.bar_date.isoformat(),
                        exit_date=exit_bar.bar_date.isoformat(),
                        horizon_sessions=horizon,
                        return_pct=round(ticker_return * 100, 4),
                        benchmark_return_pct=round(benchmark_return * 100, 4),
                        excess_return_pct=round((ticker_return - benchmark_return) * 100, 4),
                        url=candidate.url,
                    )
                )

    return results, sorted(missing)


def render_report(
    conn: sqlite3.Connection,
    evaluated_at: datetime,
    horizons: tuple[int, ...] = (1, 5, 20),
) -> tuple[str, dict[str, object]]:
    candidates = load_candidates(conn, evaluated_at)
    results, missing = evaluate_candidates(conn, candidates, evaluated_at, horizons)
    unclocked_labels = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status != 'unreviewed'"
    ).fetchone()[0]

    lines = [
        "# X point-in-time replay",
        "",
        f"Evaluated at `{evaluated_at.astimezone(UTC).isoformat()}`.",
        "",
        "## What this measures",
        "",
        "This is an event study of ticker mentions that had a recorded route or capture time. "
        "It measures what happened after the information became available to the system. The "
        "old records don't contain a bullish or bearish direction, so these returns aren't "
        "strategy PnL and can't establish prediction accuracy.",
        "",
        "## Lookahead controls",
        "",
        "- Selection uses only time-stamped route decisions and captured signals.",
        f"- {unclocked_labels} human review labels are excluded because they don't record when "
        "the label was assigned.",
        "- Availability is the latest of post, fetch, and route or capture time.",
        "- Tickers come from explicit cashtags or the ticker list saved with a captured signal.",
        "- A same-day open is allowed only when availability precedes 09:30 America/New_York. "
        "Otherwise entry moves to the next recorded session.",
        "- Horizons were fixed before viewing the results: 1, 5, and 20 sessions.",
        "",
        "## Coverage",
        "",
        f"Candidates: {len(candidates)}  ",
        f"Ticker-horizon observations: {len(results)}  ",
        f"Missing price series: {', '.join(missing) if missing else 'none'}",
        "",
        "## Results",
        "",
        "| Horizon | Events | Mean basket return | Median basket return | Mean excess vs QQQ | "
        "Mean absolute excess | Positive return rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    summaries: list[dict[str, object]] = []
    for horizon in horizons:
        bucket = [result for result in results if result.horizon_sessions == horizon]
        if not bucket:
            lines.append(f"| {horizon} | 0 | n/a | n/a | n/a | n/a | n/a |")
            continue
        exposures_by_event: dict[tuple[str, str], list[ReplayResult]] = {}
        for result in bucket:
            exposures_by_event.setdefault((result.source, result.post_id), []).append(result)
        returns = [
            mean(exposure.return_pct for exposure in exposures)
            for exposures in exposures_by_event.values()
        ]
        excess = [
            mean(exposure.excess_return_pct for exposure in exposures)
            for exposures in exposures_by_event.values()
        ]
        summary: dict[str, object] = {
            "horizon_sessions": horizon,
            "events": len(exposures_by_event),
            "ticker_exposures": len(bucket),
            "mean_return_pct": round(mean(returns), 4),
            "median_return_pct": round(median(returns), 4),
            "mean_excess_return_pct": round(mean(excess), 4),
            "mean_absolute_excess_pct": round(mean(abs(value) for value in excess), 4),
            "positive_return_rate": round(sum(value > 0 for value in returns) / len(returns), 4),
        }
        summaries.append(summary)
        lines.append(
            f"| {horizon} | {len(exposures_by_event)} | {summary['mean_return_pct']:.2f}% | "
            f"{summary['median_return_pct']:.2f}% | "
            f"{summary['mean_excess_return_pct']:.2f}% | "
            f"{summary['mean_absolute_excess_pct']:.2f}% | "
            f"{summary['positive_return_rate']:.1%} |"
        )

    lines += [
        "",
        "Each event is an equal-weight basket of the tickers in one post, which prevents a long "
        "ticker list from receiving more weight in the summary. Events still aren't independent "
        "because one ticker can appear in several posts. Treat the table as a dataset diagnostic, "
        "not a confidence interval or investable result.",
        "",
        "## Event details",
        "",
        "| Available | Source | Rank | Account | Ticker | Entry | Horizon | Exit | Return | "
        "Excess vs QQQ |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| {result.available_at} | {result.source} | {result.rank} | @{result.handle} | "
            f"{result.ticker} | {result.entry_date} | {result.horizon_sessions} | "
            f"{result.exit_date} | {result.return_pct:.2f}% | "
            f"{result.excess_return_pct:.2f}% |"
        )

    payload: dict[str, object] = {
        "evaluated_at": evaluated_at.isoformat(),
        "benchmark": _BENCHMARK,
        "horizons": list(horizons),
        "excluded_untimestamped_human_labels": unclocked_labels,
        "candidates": [asdict(candidate) for candidate in candidates],
        "missing_price_series": missing,
        "summaries": summaries,
        "results": [asdict(result) for result in results],
    }
    return "\n".join(lines) + "\n", payload


def _refresh_prices(conn: sqlite3.Connection, evaluated_at: datetime, through: date) -> None:
    candidates = load_candidates(conn, evaluated_at)
    if not candidates:
        print("no replay candidates")
        return
    tickers = sorted(
        {ticker for candidate in candidates for ticker in candidate.tickers} | {_BENCHMARK}
    )
    start = min(candidate.available_at.astimezone(_NEW_YORK).date() for candidate in candidates)
    for ticker in tickers:
        written = refresh_ticker(
            conn, ticker, start - timedelta(days=7), through + timedelta(days=1)
        )
        print(f"{ticker}: {written} bars")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.x.replay")
    parser.add_argument("--db", default="data/boustrategy.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh")
    refresh_parser.add_argument("--through", default=date.today().isoformat())

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--as-of")
    render_parser.add_argument("--out")

    args = parser.parse_args()
    conn = connect(args.db)
    evaluated_at = (
        _parse_datetime(args.as_of) if getattr(args, "as_of", None) else datetime.now(UTC)
    )
    if args.command == "refresh":
        _refresh_prices(conn, evaluated_at, date.fromisoformat(args.through))
        return

    report, payload = render_report(conn, evaluated_at)
    out = Path(args.out or f"data/replays/x-point-in-time-{evaluated_at.date().isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"rendered {out} and {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
