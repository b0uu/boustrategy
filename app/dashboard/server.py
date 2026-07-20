import argparse
from html import escape
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.dashboard import queries
from app.storage.database import connect

# Status colors are reserved for state and always ship with a text label,
# never color alone (dataviz doctrine). Everything unknown renders neutral.
_STATUS_GOOD = {"green", "order_intent_created", "policy_approved", "consumed", "summarized"}
_STATUS_WARN = {"yellow", "pending", "started", "exported", "routed"}
_STATUS_BAD = {"red", "policy_rejected", "schema_failed", "failed", "dismissed"}

_STYLE = """
:root{
  --ink:#1a1a19; --ink-2:#565654; --ink-3:#8a8a86;
  --surface:#fcfcfb; --card:#ffffff; --line:#e6e6e2;
  --good:#0ca30c; --warn:#b97900; --bad:#d03b3b; --accent:#3e6f9e;
}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;
  background:var(--surface);color:var(--ink);line-height:1.45}
main{max-width:1100px;margin:0 auto;padding:0 1.25rem 3rem}
nav{border-bottom:1px solid var(--line);background:var(--card)}
nav .inner{max-width:1100px;margin:0 auto;padding:.65rem 1.25rem;display:flex;
  gap:1.1rem;align-items:baseline;flex-wrap:wrap}
nav .brand{font-weight:600;margin-right:.5rem}
nav a{color:var(--ink-2);text-decoration:none;font-size:.92rem;padding:.15rem 0}
nav a:hover{color:var(--ink)}
nav a.active{color:var(--ink);font-weight:600;border-bottom:2px solid var(--accent)}
h1{font-size:1.35rem;margin:1.4rem 0 .9rem}
h2{font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);margin:1.8rem 0 .5rem;font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:.75rem}
a.tile{display:block;background:var(--card);border:1px solid var(--line);
  border-radius:8px;padding:.85rem 1rem;text-decoration:none;color:inherit}
a.tile:hover{border-color:var(--ink-3)}
.tile .label{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:.35rem}
.tile .value{font-size:1.45rem;font-weight:650;font-variant-numeric:tabular-nums}
.tile .sub{font-size:.82rem;color:var(--ink-2);margin-top:.25rem}
.badge{display:inline-flex;align-items:center;gap:.35em;font-size:.8rem;
  font-weight:600;padding:.05rem .5rem;border-radius:99px;
  background:#f0f0ed;color:var(--ink-2);white-space:nowrap}
.badge .dot{width:.5em;height:.5em;border-radius:50%;background:var(--ink-3)}
.badge.good{background:#e9f6e9;color:#0a6b0a}.badge.good .dot{background:var(--good)}
.badge.warn{background:#fdf3dd;color:#7a5200}.badge.warn .dot{background:#fab219}
.badge.bad{background:#fbe9e9;color:#a02020}.badge.bad .dot{background:var(--bad)}
table{border-collapse:collapse;width:100%;margin:.4rem 0 1.4rem;background:var(--card);
  border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:.9rem}
th{font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3);
  font-weight:600;text-align:left;padding:.5rem .7rem;border-bottom:1px solid var(--line)}
td{padding:.45rem .7rem;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.state-change td{background:#f6f8fa}
.empty{color:var(--ink-3);font-size:.9rem}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:1rem;white-space:pre-wrap;font-size:.85rem;overflow-x:auto}
code{font-size:.8rem;color:var(--ink-2);word-break:break-all}
.bar{height:6px;border-radius:3px;background:#eeeeea;margin-top:.5rem;overflow:hidden}
.bar span{display:block;height:100%;background:var(--accent)}
figure{margin:.4rem 0 1.2rem;background:var(--card);border:1px solid var(--line);
  border-radius:8px;padding:1rem;max-width:460px}
figure svg{width:100%;height:auto;display:block}
figcaption{font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:.5rem}
"""

_NAV = (
    ("Overview", "/"),
    ("Portfolio", "/portfolio"),
    ("Decisions", "/decisions"),
    ("Digests", "/digests"),
    ("X", "/x"),
    ("Regime", "/regime"),
    ("Triggers", "/triggers"),
)


def render_x_snippet(text: str, public: bool = False) -> str:
    """Single future public-mode seam: public surfaces must use claim summaries."""
    return "[private snippet hidden]" if public else text[:280]


def _page(title: str, body: str, active: str = "") -> str:
    links = "".join(
        f"<a href='{href}'{' class=' + chr(39) + 'active' + chr(39) if href == active else ''}>"
        f"{escape(name)}</a>"
        for name, href in _NAV
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)} — BouStrategy</title><style>{_STYLE}</style></head><body>"
        f"<nav><div class='inner'><span class='brand'>BouStrategy</span>{links}</div></nav>"
        f"<main><h1>{escape(title)}</h1>{body}</main></body></html>"
    )


def _badge(value: str) -> str:
    lowered = value.casefold()
    css = "good" if lowered in _STATUS_GOOD else "warn" if lowered in _STATUS_WARN else ""
    css = "bad" if lowered in _STATUS_BAD else css
    return f"<span class='badge {css}'><span class='dot'></span>{escape(value)}</span>"


_BADGE_COLUMNS = {"status", "regime", "raw_regime", "final_status", "rank", "parse_status"}


def _cell(name: str, value: Any) -> str:
    if value is None or value == "":
        return "<td><span class='empty'>—</span></td>"
    if name in _BADGE_COLUMNS and isinstance(value, str):
        return f"<td>{_badge(value)}</td>"
    if isinstance(value, bool):
        return f"<td>{'yes' if value else 'no'}</td>"
    if isinstance(value, float):
        return f"<td class='num'>{value:,.2f}</td>"
    if isinstance(value, int):
        return f"<td class='num'>{value:,}</td>"
    text = str(value)
    if name.endswith("_json") or (text.startswith(("{", "[")) and text.endswith(("}", "]"))):
        return f"<td><code>{escape(text)}</code></td>"
    return f"<td>{escape(text)}</td>"


def _header(name: str, sample: Any) -> str:
    numeric = isinstance(sample, (int, float)) and not isinstance(sample, bool)
    css = " class='num'" if numeric else ""
    return f"<th{css}>{escape(name.replace('_', ' '))}</th>"


def _table(items: list[dict[str, Any]] | None) -> str:
    if items is None:
        return ""
    if not items:
        return "<p class='empty'>none yet</p>"
    headers = list(items[0])
    head = "".join(_header(name, items[0][name]) for name in headers)
    body = "".join(
        "<tr>" + "".join(_cell(name, item[name]) for name in headers) + "</tr>" for item in items
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _sparkline(values: list[float] | None) -> str:
    if not values:
        return "<p class='empty'>none yet</p>"
    low, high = min(values), max(values)
    spread = high - low or 1
    width = max(len(values) - 1, 1)
    coords = [
        (index / width * 300, 100 - (value - low) / spread * 90 - 5)
        for index, value in enumerate(values)
    ]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]
    return (
        "<figure><figcaption>Equity</figcaption>"
        "<svg viewBox='0 0 300 100' role='img' aria-label='equity over time'>"
        f"<polyline points='{points}' fill='none' stroke='#3e6f9e' stroke-width='2' "
        "stroke-linejoin='round' stroke-linecap='round'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='3.5' fill='#3e6f9e'/></svg>"
        f"<div class='sub'>latest {values[-1]:,.2f}</div></figure>"
    )


def _regime_table(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return _table(items)
    rows = []
    for index, item in enumerate(items):
        older_regime = items[index + 1]["regime"] if index + 1 < len(items) else None
        css = " class='state-change'" if item["regime"] != older_regime else ""
        cells = "".join(_cell(name, value) for name, value in item.items())
        rows.append(f"<tr{css}>{cells}</tr>")
    headers = "".join(_header(name, items[0][name]) for name in items[0])
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _tile(href: str, label: str, value: str, sub: str = "") -> str:
    sub_html = f"<div class='sub'>{sub}</div>" if sub else ""
    return (
        f"<a class='tile' href='{href}'><div class='label'>{escape(label)}</div>"
        f"<div class='value'>{value}</div>{sub_html}</a>"
    )


def _overview_tiles(payload: dict[str, Any]) -> str:
    tiles: list[str] = []

    paper = payload.get("paper")
    if paper:
        delta = paper["equity"] - paper["starting"]
        sign = "+" if delta >= 0 else "−"
        tiles.append(
            _tile(
                "/portfolio",
                "Paper equity",
                f"${paper['equity']:,.0f}",
                f"cash ${paper['cash']:,.0f} · {sign}${abs(delta):,.0f} vs start",
            )
        )

    regime = payload.get("regime")
    regime_sub = (
        f"score {regime['score']} · {escape(regime['snapshot_date'])}"
        if regime
        else "no snapshot yet"
    )
    tiles.append(
        _tile(
            "/regime",
            "Regime",
            _badge(regime["regime"]) if regime else "<span class='empty'>—</span>",
            regime_sub,
        )
    )

    reads = payload.get("x_reads")
    if reads:
        total = reads["used"] + reads["remaining"]
        pct = int(reads["used"] / total * 100) if total else 0
        tiles.append(
            _tile(
                "/x",
                "X reads this month",
                f"{reads['remaining']:,} <span class='sub'>left</span>",
                f"{reads['used']:,} used of {total:,}"
                f"<div class='bar'><span style='width:{pct}%'></span></div>",
            )
        )

    for key, href, label in (
        ("pending_triggers", "/triggers", "Pending triggers"),
        ("pending_articles", "/x", "Pending articles"),
    ):
        if key in payload:
            tiles.append(_tile(href, label, f"{payload[key]:,}"))

    last_digest = payload.get("last_digest")
    tiles.append(
        _tile(
            "/digests",
            "Last digest",
            escape(last_digest) if last_digest else "<span class='empty'>none yet</span>",
        )
    )

    statuses: dict[str, int] = payload.get("decision_statuses") or {}
    if statuses:
        lines = "".join(
            f"<div class='sub'>{_badge(status)} {count:,}</div>"
            for status, count in sorted(statuses.items())
        )
        tiles.append(_tile("/decisions", "Decisions", f"{sum(statuses.values()):,}", lines))
    else:
        tiles.append(_tile("/decisions", "Decisions", "0", "none yet"))

    return f"<div class='tiles'>{''.join(tiles)}</div>"


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="BouStrategy dashboard")
    path = Path(db_path)
    digest_dir = path.parent / "digests"

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        conn = connect(path)
        payload = queries.overview(conn, digest_dir)
        return _page("Overview", _overview_tiles(payload), active="/")

    @app.get("/portfolio", response_class=HTMLResponse)
    def portfolio() -> str:
        conn = connect(path)
        payload = queries.portfolio(conn)
        return _page(
            "Portfolio",
            _sparkline(payload["equity_series"])
            + "<h2>Positions</h2>"
            + _table(payload["positions"])
            + "<h2>Fills</h2>"
            + _table(payload["fills"]),
            active="/portfolio",
        )

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions() -> str:
        conn = connect(path)
        return _page("Decisions", _table(queries.decisions(conn)), active="/decisions")

    @app.get("/digests", response_class=HTMLResponse)
    def digests(file: str | None = None) -> str:
        if file is not None:
            selected = digest_dir / Path(file).name
            if not selected.exists():
                raise HTTPException(404, "digest not found")
            return _page(
                file,
                f"<pre>{escape(selected.read_text(encoding='utf-8'))}</pre>",
                active="/digests",
            )
        items = (
            [{"file": item.name} for item in sorted(digest_dir.glob("*.md"), reverse=True)]
            if digest_dir.exists()
            else []
        )
        listing = (
            "".join(
                f"<p><a href='/digests?file={escape(item['file'])}'>{escape(item['file'])}</a></p>"
                for item in items
            )
            if items
            else "<p class='empty'>none yet</p>"
        )
        return _page("Digests", listing, active="/digests")

    @app.get("/x", response_class=HTMLResponse)
    def x_page() -> str:
        conn = connect(path)
        payload = queries.x_data(conn)
        sections = "".join(
            f"<h2>{escape(name)}</h2>" + _table(value) for name, value in payload.items()
        )
        return _page("X", sections, active="/x")

    @app.get("/regime", response_class=HTMLResponse)
    def regime() -> str:
        conn = connect(path)
        return _page("Regime", _regime_table(queries.regime(conn)), active="/regime")

    @app.get("/triggers", response_class=HTMLResponse)
    def triggers() -> str:
        conn = connect(path)
        return _page("Triggers", _table(queries.triggers(conn)), active="/triggers")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.dashboard.server")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--port", type=int, default=8378)
    args = parser.parse_args()
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
