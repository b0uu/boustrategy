import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from app.events.store import upcoming_events
from app.paper.broker import cash_balance
from app.paper.context import _latest_close, portfolio_context

_DAILY_DIGEST = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_RULES_BANNER = "RULES NOT YET SIGNED OFF"


def _digest_headlines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    actionable = False
    headlines: list[str] = []
    for line in lines:
        if line.strip().casefold().startswith("## actionable"):
            actionable = True
            continue
        if actionable and line.startswith("## "):
            break
        if actionable and line.strip().startswith(("- ", "* ")):
            headlines.append(line.strip())
    return headlines


def build_intake(
    conn: sqlite3.Connection,
    on_date: date,
    out_dir: str | Path,
    digest_dir: str | Path = "data/digests",
    *,
    rules_signed_off: bool = True,
) -> Path:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)

    regime = conn.execute(
        """
        SELECT snapshot_date, regime, raw_regime, score, components_json
        FROM regime_snapshots WHERE snapshot_date <= ?
        ORDER BY snapshot_date DESC LIMIT 1
        """,
        (on_date.isoformat(),),
    ).fetchone()
    triggers = [
        {
            "trigger_id": row[0],
            "trigger_type": row[1],
            "subject": row[2],
            "fired_at": row[3],
            "details": json.loads(row[4]),
        }
        for row in conn.execute(
            """
            SELECT trigger_id, trigger_type, subject, fired_at, details_json
            FROM trigger_events
            WHERE status = 'pending' AND substr(fired_at, 1, 10) <= ?
            ORDER BY fired_at, trigger_id
            """,
            (on_date.isoformat(),),
        )
    ]
    articles = [
        {"post_id": row[0], "queued_at": row[1], "url": row[2], "text": row[3]}
        for row in conn.execute(
            """
            SELECT q.post_id, q.queued_at, p.url, p.text
            FROM x_article_queue q JOIN x_posts p ON p.post_id = q.post_id
            WHERE q.status = 'pending' AND substr(q.queued_at, 1, 10) <= ?
            ORDER BY q.queued_at, q.post_id
            """,
            (on_date.isoformat(),),
        )
    ]
    positions = []
    positions_value = 0.0
    for ticker, shares, avg_cost, theme in conn.execute(
        "SELECT ticker, shares, avg_cost, primary_theme_id FROM paper_positions ORDER BY ticker"
    ):
        close = _latest_close(conn, ticker, on_date)
        market_value = float(shares) * close
        positions_value += market_value
        positions.append(
            {
                "ticker": ticker,
                "shares": shares,
                "avg_cost": avg_cost,
                "latest_close": close,
                "market_value": market_value,
                "primary_theme_id": theme,
            }
        )
    cash = cash_balance(conn, on_date)
    quota = portfolio_context(conn, on_date)
    portfolio = {
        "as_of": on_date.isoformat(),
        "positions": positions,
        "cash": cash,
        "equity": cash + positions_value,
        "quota_state": quota.model_dump(),
    }
    calendar = upcoming_events(conn, on_date, 7)

    digest_root = Path(digest_dir)
    digest_paths = (
        sorted(
            (
                path
                for path in digest_root.iterdir()
                if path.is_file()
                and _DAILY_DIGEST.fullmatch(path.name)
                and path.stem <= on_date.isoformat()
            ),
            reverse=True,
        )[:3]
        if digest_root.exists()
        else []
    )

    (output / "portfolio.json").write_text(
        json.dumps(portfolio, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "triggers.json").write_text(
        json.dumps(triggers, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = ["# Reasoning intake bundle", "", f"As of: {on_date.isoformat()}", ""]
    lines.extend(["## Regime", ""])
    if not rules_signed_off:
        lines.extend([f"> **{_RULES_BANNER}**", ""])
    if regime is None:
        lines.append("No published regime snapshot.")
    else:
        lines.extend(
            [
                f"- Published: {regime[0]}",
                f"- Regime: {regime[1]} (raw: {regime[2]})",
                f"- Score: {regime[3]}",
                f"- Components: `{json.dumps(json.loads(regime[4]), sort_keys=True)}`",
            ]
        )
    lines.extend(["", "## Pending triggers", ""])
    lines.extend(
        f"- `{item['trigger_id']}`: {item['trigger_type']} / {item['subject']} / "
        f"{json.dumps(item['details'], sort_keys=True)}"
        for item in triggers
    )
    if not triggers:
        lines.append("None.")
    lines.extend(["", "## Recent daily digests", ""])
    for path in digest_paths:
        lines.append(f"### `{path.as_posix()}`")
        headlines = _digest_headlines(path)
        lines.extend(headlines or ["- No ACTIONABLE headline items."])
        lines.append("")
    if not digest_paths:
        lines.append("None.")
    lines.extend(["", "## Pending article queue", ""])
    lines.extend(
        f"- `{item['post_id']}` ({item['queued_at']}): {item['url']} — {item['text']}"
        for item in articles
    )
    if not articles:
        lines.append("None.")
    lines.extend(["", "## Paper portfolio", ""])
    lines.extend(
        f"- {item['ticker']}: {item['shares']} shares, value {item['market_value']:.2f}, "
        f"theme {item['primary_theme_id'] or 'none'}"
        for item in positions
    )
    if not positions:
        lines.append("- No positions.")
    lines.extend([f"- Cash: {cash:.2f}", f"- Equity: {portfolio['equity']:.2f}"])
    lines.extend(["", "## Today's intake quota state", ""])
    for key, value in quota.model_dump().items():
        lines.append(f"- {key}: `{json.dumps(value, sort_keys=True)}`")
    lines.extend(["", "## Upcoming calendar (7 days)", ""])
    lines.extend(
        f"- {event_date}: {event_type} {ticker or 'FOMC'} — {label}"
        for event_date, event_type, ticker, label in calendar
    )
    if not calendar:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Required runtime reading",
            "",
            "- `docs/mandate.md`",
            "- `docs/risk_policy.md`",
            "- `docs/risk_posture.md`",
            "- `docs/source_policy.md`",
            "- `docs/prompts/thesis_chain.md`",
            "- `docs/prompts/daily_management.md`",
        ]
    )
    bundle_path = output / "bundle.md"
    bundle_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return bundle_path
