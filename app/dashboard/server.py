import argparse
import secrets
import sqlite3
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.dashboard import queries
from app.reason.run import PreparationResult, prepare_session
from app.storage.database import connect

# Status colors are reserved for state and always ship with a text label,
# never color alone (dataviz doctrine). Everything unknown renders neutral.
_STATUS_GOOD = {
    "green",
    "order_intent_created",
    "policy_approved",
    "consumed",
    "summarized",
    "ready",
}
_STATUS_WARN = {
    "yellow",
    "pending",
    "started",
    "exported",
    "routed",
    "awaiting_execution",
    "awaiting_price",
}
_STATUS_BAD = {"red", "policy_rejected", "schema_failed", "failed", "dismissed", "missing"}

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
.operator-grid{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr);
  gap:1rem;align-items:start}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:1.1rem 1.2rem;margin-bottom:1rem;box-shadow:0 14px 35px rgba(28,31,27,.035)}
.panel h2{margin:.1rem 0 .8rem}.panel p{color:var(--ink-2);margin:.45rem 0}
.step{display:grid;grid-template-columns:2rem minmax(0,1fr);gap:.75rem}
.step-number{width:2rem;height:2rem;border:1px solid var(--ink);border-radius:50%;
  display:grid;place-items:center;font:700 .8rem Georgia,serif}
.controls{display:flex;gap:.7rem;align-items:end;flex-wrap:wrap;margin:.8rem 0}
label{display:grid;gap:.3rem;font-size:.74rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);font-weight:650}
input,select{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);
  border-radius:6px;padding:.55rem .65rem;min-height:2.35rem}
button,.button{appearance:none;border:1px solid var(--ink);background:var(--ink);color:white;
  border-radius:6px;padding:.58rem .9rem;font:650 .84rem/1 inherit;cursor:pointer;
  text-decoration:none}
button:hover,.button:hover{background:#343431}.button.secondary{background:transparent;color:var(--ink)}
.button.secondary:hover{background:#f2f2ed}.button:disabled,button:disabled{opacity:.42;cursor:not-allowed}
.prompt{max-height:13rem;overflow:auto;background:#f7f7f3;border-color:#deded7;font-size:.78rem}
.notice,.error{border-radius:7px;padding:.7rem .85rem;margin:.75rem 0;font-size:.88rem}
.notice{background:#edf7ed;color:#125f1b;border:1px solid #cce5cd}
.error{background:#fff0ef;color:#8d2525;border:1px solid #efcfcc}
.status-list{display:grid;gap:.55rem}.status-row{display:flex;justify-content:space-between;
  gap:1rem;padding-bottom:.5rem;border-bottom:1px solid var(--line);font-size:.86rem}
.status-row:last-child{border-bottom:0;padding-bottom:0}
.status-row span:first-child{color:var(--ink-2)}
.quiet{font-size:.78rem;color:var(--ink-3)}
@media(max-width:760px){.operator-grid{grid-template-columns:1fr}nav .inner{gap:.75rem}}
"""

_NAV = (
    ("Overview", "/"),
    ("Operate", "/operate"),
    ("Portfolio", "/portfolio"),
    ("Decisions", "/decisions"),
    ("Executions", "/executions"),
    ("Digests", "/digests"),
    ("X", "/x"),
    ("Regime", "/regime"),
    ("Triggers", "/triggers"),
)

_SLOTS = {"morning", "midday", "close"}
_NEW_YORK = ZoneInfo("America/New_York")


class PreparationRunner(Protocol):
    def __call__(
        self,
        conn: sqlite3.Connection,
        on_date: date,
        out_dir: str | Path,
        *,
        digest_dir: str | Path = "data/digests",
        watchlist_path: str | Path = "docs/watchlist.md",
    ) -> PreparationResult: ...


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
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} — BouStrategy</title><style>{_STYLE}</style></head><body>"
        f"<nav><div class='inner'><span class='brand'>BouStrategy</span>{links}</div></nav>"
        f"<main><h1>{escape(title)}</h1>{body}</main>"
        "<script>document.querySelectorAll('[data-copy]').forEach((button)=>{"
        "button.addEventListener('click',async()=>{const node=document.getElementById("
        "button.dataset.copy);await navigator.clipboard.writeText(node.innerText);"
        "const old=button.innerText;button.innerText='Copied';setTimeout(()=>button.innerText=old,"
        "1200);});});</script></body></html>"
    )


def _badge(value: str) -> str:
    lowered = value.casefold()
    css = "good" if lowered in _STATUS_GOOD else "warn" if lowered in _STATUS_WARN else ""
    css = "bad" if lowered in _STATUS_BAD else css
    return f"<span class='badge {css}'><span class='dot'></span>{escape(value)}</span>"


def _copy_button(target: str, label: str, enabled: bool = True) -> str:
    disabled = "" if enabled else " disabled"
    return (
        f"<button type='button' class='button secondary' data-copy='{target}'{disabled}>"
        f"{escape(label)}</button>"
    )


def _operator_body(
    status: dict[str, Any], csrf_token: str, slot: str, notice: str = "", error: str = ""
) -> str:
    day = str(status["date"])
    digester_prompt = (
        f"Follow docs/x_pipeline/DIGESTER.md for {day} using the {slot} slot. This is a "
        "supervised manual run. Stop after the digest is rendered and verified. Don't continue "
        "into investment reasoning."
    )
    reasoning_prompt = (
        f"Follow docs/reasoning/RUNBOOK.md for {day} using data/reason_runs/{day}/bundle.md "
        f"and its preparation.json receipt. This is the {slot} paper reasoning pass. First "
        "review existing positions, pending order intents, prior same-day decisions, and the "
        "remaining daily quota. Don't resubmit an existing decision record or treat a pending "
        "intent as a filled position. Then select the 2-3 strongest eligible U.S.-listed "
        "candidates and actively research independent primary or reputable sources plus current "
        "price context before applying the complete thesis chain. Treat missing outside-X "
        "confirmation as a research task, not an automatic reason to reject a candidate. Give "
        "each new record the actual current timestamp, never a future timestamp, and submit it "
        "exactly once. Append a distinct timestamped section for this pass to the "
        "reasoning-session log even if none survives the research and the correct result is no "
        "action. Don't force a trade. Show me every new decision record and submission result."
    )
    runs = status["runs"]
    run_summary = (
        ", ".join(f"{run['slot']}: {run['status']}" for run in runs) if runs else "none recorded"
    )
    receipt = status["receipt"] or {}
    receipt_summary = (
        f"{receipt.get('fills_created', 0)} fills, "
        f"{receipt.get('intents_awaiting_price', 0)} awaiting, "
        f"regime {receipt.get('regime', 'unknown')}"
        if receipt
        else "not prepared"
    )
    notice_html = f"<div class='notice'>{escape(notice)}</div>" if notice else ""
    error_html = f"<div class='error'>{escape(error)}</div>" if error else ""
    prepare_disabled = "" if status["digest_ready"] else " disabled"
    prepare_help = (
        "Ready. This may take a minute while market data refreshes."
        if status["digest_ready"]
        else "Complete and render the same-day digest first."
    )
    slot_options = "".join(
        f"<option value='{item}'{' selected' if item == slot else ''}>{item}</option>"
        for item in sorted(_SLOTS)
    )
    digest_state = "ready" if status["digest_exists"] else "missing"
    preparation_state = "ready" if status["prepared"] else "pending"
    return "".join(
        [
            "<div class='operator-grid'><section>",
            "<div class='panel'><div class='step'><div class='step-number'>1</div><div>",
            "<h2>Digest the feed</h2>",
            "<p>Copy this into a fresh agent session. Nothing runs or spends X credits until "
            "you start that separate session.</p>",
            f"<pre class='prompt' id='digester-prompt'>{escape(digester_prompt)}</pre>",
            _copy_button("digester-prompt", "Copy digester prompt"),
            "</div></div></div>",
            "<div class='panel'><div class='step'><div class='step-number'>2</div><div>",
            "<h2>Prepare the paper session</h2>",
            "<p>Refresh market and calendar data, settle eligible paper intents, evaluate "
            "triggers, score the regime, and create the intake receipt. This doesn't read X or "
            "contact a broker.</p>",
            notice_html,
            error_html,
            "<form method='post' action='/operate/prepare'>",
            f"<input type='hidden' name='csrf_token' value='{escape(csrf_token)}'>",
            f"<input type='hidden' name='date' value='{escape(day)}'>",
            f"<input type='hidden' name='slot' value='{escape(slot)}'>",
            f"<button type='submit'{prepare_disabled}>Prepare paper session</button>",
            "</form>",
            f"<p class='quiet'>{escape(prepare_help)}</p>",
            "</div></div></div>",
            "<div class='panel'><div class='step'><div class='step-number'>3</div><div>",
            "<h2>Run investment reasoning</h2>",
            "<p>Use a fresh agent only after preparation succeeds.</p>",
            f"<pre class='prompt' id='reasoning-prompt'>{escape(reasoning_prompt)}</pre>",
            _copy_button("reasoning-prompt", "Copy reasoning prompt", status["prepared"]),
            "</div></div></div></section><aside>",
            "<div class='panel'><h2>Session controls</h2>",
            "<form method='get' action='/operate'><div class='controls'>",
            f"<label>Date<input type='date' name='date' value='{escape(day)}'></label>",
            f"<label>Slot<select name='slot'>{slot_options}</select></label>",
            "<button type='submit' class='button secondary'>Load</button>",
            "</div></form></div>",
            "<div class='panel'><h2>Readiness</h2><div class='status-list'>",
            "<div class='status-row'><span>Digest file</span>",
            _badge(digest_state),
            "</div><div class='status-row'><span>Database runs</span>",
            f"<strong>{escape(run_summary)}</strong></div>",
            "<div class='status-row'><span>Preparation</span>",
            _badge(preparation_state),
            "</div><div class='status-row'><span>Receipt</span>",
            f"<strong>{escape(receipt_summary)}</strong></div></div></div>",
            "<div class='panel'><h2>Safety boundary</h2>",
            "<p class='quiet'>Paper only. Scheduled tasks remain disabled. The dashboard has no "
            "live-broker connection and can't enable one.</p></div>",
            "</aside></div>",
        ]
    )


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

    if "live_intents_awaiting_execution" in payload:
        tiles.append(
            _tile(
                "/executions",
                "Live intents awaiting execution",
                f"{payload['live_intents_awaiting_execution']:,}",
                "live placement disabled",
            )
        )

    return f"<div class='tiles'>{''.join(tiles)}</div>"


def create_app(
    db_path: str | Path, preparation_runner: PreparationRunner = prepare_session
) -> FastAPI:
    app = FastAPI(title="BouStrategy dashboard")
    path = Path(db_path)
    digest_dir = path.parent / "digests"
    reason_dir = path.parent / "reason_runs"
    csrf_token = secrets.token_urlsafe(24)

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        conn = connect(path)
        payload = queries.overview(conn, digest_dir)
        return _page("Overview", _overview_tiles(payload), active="/")

    @app.get("/operate", response_class=HTMLResponse)
    def operate(
        run_date: str | None = Query(default=None, alias="date"),
        slot: str = "close",
        notice: str = "",
    ) -> str:
        today = datetime.now(_NEW_YORK).date()
        try:
            selected_date = today if run_date is None else date.fromisoformat(run_date)
        except ValueError:
            selected_date = today
        selected_slot = slot if slot in _SLOTS else "close"
        conn = connect(path)
        status = queries.operator_status(conn, digest_dir, reason_dir, selected_date)
        return _page(
            "Manual paper cycle",
            _operator_body(status, csrf_token, selected_slot, notice=notice),
            active="/operate",
        )

    @app.post("/operate/prepare", response_class=HTMLResponse)
    async def prepare(request: Request) -> Response:
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        submitted_token = form.get("csrf_token", [""])[0]
        if not secrets.compare_digest(submitted_token, csrf_token):
            raise HTTPException(403, "invalid request token")

        run_date = form.get("date", [""])[0]
        slot = form.get("slot", ["close"])[0]
        selected_slot = slot if slot in _SLOTS else "close"
        try:
            selected_date = date.fromisoformat(run_date)
        except ValueError as error:
            raise HTTPException(400, "invalid session date") from error
        if selected_date > datetime.now(_NEW_YORK).date():
            raise HTTPException(400, "session date can't be in the future")

        conn = connect(path)
        try:
            preparation_runner(
                conn,
                selected_date,
                reason_dir / run_date,
                digest_dir=digest_dir,
            )
        except Exception as error:
            status = queries.operator_status(conn, digest_dir, reason_dir, selected_date)
            return HTMLResponse(
                _page(
                    "Manual paper cycle",
                    _operator_body(
                        status,
                        csrf_token,
                        selected_slot,
                        error=f"Preparation failed: {type(error).__name__}: {error}",
                    ),
                    active="/operate",
                ),
                status_code=400,
            )

        query = urlencode(
            {
                "date": run_date,
                "slot": selected_slot,
                "notice": "Preparation completed.",
            }
        )
        return RedirectResponse(f"/operate?{query}", status_code=303)

    @app.get("/portfolio", response_class=HTMLResponse)
    def portfolio() -> str:
        conn = connect(path)
        payload = queries.portfolio(conn)
        return _page(
            "Portfolio",
            _sparkline(payload["equity_series"])
            + "<h2>Positions</h2>"
            + _table(payload["positions"])
            + "<h2>Order intents</h2>"
            + _table(payload["intents"])
            + "<h2>Fills</h2>"
            + _table(payload["fills"]),
            active="/portfolio",
        )

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions() -> str:
        conn = connect(path)
        return _page("Decisions", _table(queries.decisions(conn)), active="/decisions")

    @app.get("/executions", response_class=HTMLResponse)
    def executions() -> str:
        conn = connect(path)
        body = (
            "<div class='notice'>Live placement is disabled. This page is an append-only "
            "broker execution ledger, not an order-entry surface.</div>"
            "<h2>Execution records</h2>"
            + _table(queries.executions(conn))
            + "<h2>Lifecycle events</h2>"
            + _table(queries.execution_events(conn))
        )
        return _page("Broker executions", body, active="/executions")

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
