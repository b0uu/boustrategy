# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

_STATUS_GOOD = {
    "available",
    "clear",
    "consumed",
    "decisions_authored",
    "filled",
    "green",
    "order_intent_created",
    "passed",
    "policy_approved",
    "ready",
    "reviewed",
    "schema_validated",
    "submitted",
    "summarized",
}
_STATUS_WARN = {
    "awaiting_execution",
    "awaiting_price",
    "exported",
    "no_action",
    "partially_filled",
    "pending",
    "prepared",
    "routed",
    "started",
    "watchlist",
    "yellow",
}
_STATUS_BAD = {
    "blocked",
    "canceled",
    "dismissed",
    "failed",
    "missing",
    "policy_rejected",
    "red",
    "rejected",
    "schema_failed",
    "unavailable",
}

_STYLE = """
:root{
  color-scheme:dark;
  --bg:oklch(0.15 0.004 260);--surface:oklch(0.185 0.005 260);
  --surface-2:oklch(0.22 0.006 260);--border:oklch(0.30 0.006 260);
  --border-soft:oklch(0.25 0.006 260);--text:oklch(0.93 0.003 260);
  --text-2:oklch(0.68 0.008 260);--text-3:oklch(0.50 0.008 260);
  --indigo:oklch(0.75 0.13 265);--indigo-bg:oklch(0.28 0.05 265);
  --coral:oklch(0.72 0.15 25);--coral-bg:oklch(0.30 0.06 25);
  --green:oklch(0.75 0.15 150);--green-bg:oklch(0.28 0.06 150);
  --amber:oklch(0.78 0.13 85);--amber-bg:oklch(0.30 0.06 85);
  --sans:"IBM Plex Sans","Segoe UI",sans-serif;
  --mono:"IBM Plex Mono","Cascadia Mono",Consolas,monospace;
}
*{box-sizing:border-box}
html{background:var(--bg);scrollbar-color:var(--border) var(--bg)}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 var(--sans)}
a{color:var(--indigo);text-underline-offset:3px}a:hover{color:oklch(0.85 0.13 265)}
button,input,select{font:inherit}::selection{background:oklch(0.6 0.13 265/.3)}
.skip-link{position:fixed;left:12px;top:-60px;z-index:20;background:var(--text);color:var(--bg);
  padding:8px 12px;border-radius:4px}.skip-link:focus{top:12px}
.site-header{position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-soft);
  background:oklch(0.15 0.004 260/.94);backdrop-filter:blur(14px)}
.nav-shell{max-width:1120px;margin:auto;display:flex;align-items:center;gap:22px;padding:0 20px}
.brand{color:var(--text);font:600 13px var(--mono);letter-spacing:.02em;text-decoration:none;
  padding:14px 0;white-space:nowrap}.brand-mark{color:var(--indigo)}
.nav-links{display:flex;gap:18px;overflow-x:auto;scrollbar-width:none}.nav-links::-webkit-scrollbar{display:none}
.nav-links a{position:relative;color:var(--text-3);font-size:12.5px;text-decoration:none;
  padding:15px 0 14px;white-space:nowrap}.nav-links a:hover{color:var(--text-2)}
.nav-links a[aria-current="page"]{color:var(--text)}
.nav-links a[aria-current="page"]::after{content:"";position:absolute;left:0;right:0;bottom:-1px;
  height:2px;background:var(--indigo)}
main{width:100%;max-width:760px;margin:auto;padding:32px 24px 64px}
main.wide{max-width:1040px}
.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
  border-bottom:1px solid var(--border-soft);padding:0 4px 18px;margin-bottom:10px}
.eyebrow,.section-label{color:var(--text-3);font-size:11.5px;letter-spacing:.015em}
h1{font-size:22px;line-height:1.2;letter-spacing:-.02em;margin:4px 0 0}h2{font-size:14px;margin:0}
p{margin:0}.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.muted{color:var(--text-2)}.quiet,.empty{color:var(--text-3);font-size:12px}.empty{padding:16px 0}
.mono,.metric-value,.definition-row dd{overflow-wrap:anywhere}
.lede{font-size:13.5px;color:var(--text-2);line-height:1.65;max-width:650px}
.section{padding:24px 4px;border-bottom:1px solid var(--border-soft)}
.section:last-child{border-bottom:0}.section-label{margin-bottom:12px}
.stats{display:flex;align-items:flex-end;gap:30px;flex-wrap:wrap;padding:22px 4px 26px}
.stat-value{font:600 21px var(--mono);font-variant-numeric:tabular-nums}.stat-label{font-size:11.5px;
  color:var(--text-3);margin-top:2px}.positive{color:var(--green)}.negative{color:var(--coral)}
.status{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;
  padding:3px 9px;border-radius:4px;background:var(--surface-2);color:var(--text-2);white-space:nowrap}
.status::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.status.good{background:var(--green-bg);color:var(--green)}
.status.warn{background:var(--amber-bg);color:var(--amber)}
.status.bad{background:var(--coral-bg);color:var(--coral)}
.status.indigo{background:var(--indigo-bg);color:var(--indigo)}
.mode-strip,.notice,.error{display:flex;gap:10px;align-items:flex-start;padding:10px 12px;
  margin:12px 0;border-left:2px solid var(--indigo);background:var(--surface);font-size:12.5px;
  color:var(--text-2)}.mode-strip strong{color:var(--text);font-weight:600}
.notice{border-color:var(--green)}.error{border-color:var(--coral);color:var(--coral)}
.tabs{display:flex;gap:24px;border-bottom:1px solid var(--border-soft);margin-top:8px}
.tabs a{color:var(--text-3);font-size:13px;text-decoration:none;padding:12px 0 10px}
.tabs a.active{color:var(--text);border-bottom:2px solid var(--indigo);margin-bottom:-1px}
details{border-bottom:1px solid var(--border-soft)}summary{list-style:none;cursor:pointer}
summary::-webkit-details-marker{display:none}summary:focus-visible,a:focus-visible,button:focus-visible,
input:focus-visible,select:focus-visible{outline:2px solid var(--indigo);outline-offset:3px}
.position-summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:18px;
  align-items:center;padding:13px 2px}.position-title{display:flex;align-items:baseline;gap:12px;min-width:0}
.chevron{color:var(--text-3);width:14px}.chevron::before{content:"+"}details[open] .chevron::before{content:"−"}
.ticker{font:600 13px var(--mono);color:var(--text);min-width:50px}.position-meta{font:12px var(--mono);
  color:var(--text-3);font-variant-numeric:tabular-nums}.position-detail{padding:0 28px 18px}
.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:14px}
.metric-label{font-size:11px;color:var(--text-3)}.metric-value{font:12.5px var(--mono);margin-top:2px}
.feed-item{padding:18px 2px;border-bottom:1px solid var(--border-soft)}.feed-item:last-child{border-bottom:0}
.feed-head,.feed-meta,.split{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  flex-wrap:wrap}.feed-title{display:flex;align-items:baseline;gap:9px}.feed-time{font-size:11.5px;color:var(--text-3)}
.split>*{min-width:0}
.feed-summary{font-size:13px;color:var(--text-2);line-height:1.6;padding:10px 12px;background:var(--surface);
  border:1px solid var(--border-soft);border-radius:6px;margin:10px 0}.feed-meta{justify-content:flex-start}
.feed-meta a{font-size:12px;margin-left:auto;text-decoration:none}
.overview-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:30px}.compact-list{display:grid;gap:0}
.compact-row{display:flex;justify-content:space-between;gap:14px;padding:10px 0;
  border-bottom:1px solid var(--border-soft);font-size:12.5px}.compact-row:last-child{border-bottom:0}
.spark{margin:8px 0 0}.spark svg{display:block;width:100%;height:104px}.spark figcaption{font-size:11.5px;
  color:var(--text-3);display:flex;justify-content:space-between}.spark .area{fill:var(--indigo);opacity:.09}
.spark .line{fill:none;stroke:var(--indigo);stroke-width:1.6;vector-effect:non-scaling-stroke}
.panel{padding:18px;border:1px solid var(--border-soft);border-radius:8px;background:var(--surface);min-width:0;
  margin-bottom:14px}.panel h2{margin-bottom:8px}.panel p{color:var(--text-2);font-size:12.5px}
.operator-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);gap:20px;
  align-items:start}.live-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.step{display:grid;grid-template-columns:28px minmax(0,1fr);gap:12px}.step-number{width:24px;height:24px;
  border:1px solid var(--border);border-radius:50%;display:grid;place-items:center;font:600 11px var(--mono)}
.controls{display:flex;align-items:end;gap:10px;flex-wrap:wrap}.controls label{display:grid;gap:4px;color:var(--text-3);
  font-size:11px}.controls input,.controls select{color:var(--text);background:var(--bg);border:1px solid var(--border);
  border-radius:4px;padding:7px 9px;min-height:36px}
button,.button{appearance:none;border:1px solid var(--indigo);border-radius:4px;background:var(--indigo-bg);
  color:var(--indigo);padding:8px 11px;font-size:12px;font-weight:600;cursor:pointer;text-decoration:none}
button:hover,.button:hover{background:oklch(0.33 0.06 265)}button:disabled{cursor:not-allowed;opacity:.45}
.secondary{border-color:var(--border);background:var(--surface-2);color:var(--text-2)}
.prompt{max-height:180px;overflow:auto;white-space:pre-wrap;word-break:break-word;background:var(--bg);
  border:1px solid var(--border-soft);border-radius:5px;padding:11px;margin:10px 0;font:11.5px/1.55 var(--mono);
  color:var(--text-2)}.control-note{display:block;margin-top:7px;color:var(--amber);font-size:11.5px}
.status-list{display:grid}.status-row{display:flex;justify-content:space-between;gap:12px;padding:9px 0;
  border-bottom:1px solid var(--border-soft);font-size:12px}.status-row:last-child{border:0}
.table-wrap{overflow-x:auto;margin:8px 0 20px;border-top:1px solid var(--border-soft)}
table{border-collapse:collapse;width:100%;font-size:12px}th{color:var(--text-3);font-weight:500;text-align:left;
  padding:9px 8px;border-bottom:1px solid var(--border)}td{padding:10px 8px;border-bottom:1px solid var(--border-soft);
  vertical-align:top;color:var(--text-2)}td.num,th.num{text-align:right;font-family:var(--mono)}
td code{font:11px var(--mono);word-break:break-word}.state-change td{background:var(--surface)}
.back-link{display:inline-block;color:var(--text-3);font-size:12.5px;text-decoration:none;margin-bottom:16px}
.trace-head{padding:0 4px 22px;border-bottom:1px solid var(--border-soft)}.trace-title{display:flex;
  align-items:center;gap:10px;flex-wrap:wrap}.trace-time{margin-left:auto;color:var(--text-3);font-size:11.5px}
.thesis-callout{display:flex;gap:13px;padding:22px 4px}.thesis-dot{width:8px;height:8px;border-radius:50%;
  background:var(--green);flex:none;margin-top:7px}.thesis-text{font-size:13.5px;line-height:1.65}
.trace-rail,.pipeline-rail{display:flex;align-items:flex-start;margin:18px 0;overflow-x:auto;padding:0 6px 4px}
.trace-step{position:relative;flex:1;min-width:94px;border:0;background:none;color:var(--text-3);padding:18px 4px 0;
  font-size:10.5px;font-weight:500}.trace-step::before{content:"";position:absolute;top:4px;left:0;right:0;height:2px;
  background:var(--border)}.trace-step::after{content:"";position:absolute;top:0;left:calc(50% - 5px);width:10px;
  height:10px;border-radius:50%;background:var(--border)}.trace-step[aria-selected="true"]{color:var(--indigo)}
.trace-step[aria-selected="true"]::before,.trace-step[aria-selected="true"]::after{background:var(--indigo)}
.trace-panel{background:var(--surface);border:1px solid var(--border-soft);border-radius:8px;padding:15px 17px;
  color:var(--text-2);font-size:13px;line-height:1.65}.trace-panel[hidden]{display:none}
.source summary{display:grid;grid-template-columns:70px minmax(0,1fr) auto;gap:12px;padding:10px 2px;
  align-items:baseline}.source-type{font-size:11px;color:var(--text-3)}.confidence{font:11px var(--mono);color:var(--text-3)}
.source-detail{padding:0 0 12px 84px;color:var(--text-3);font-size:11.5px}.criteria{display:grid;gap:8px;padding:0;
  margin:0;list-style:none}.criteria li{display:flex;gap:8px;color:var(--text-2);font-size:12.5px}.criteria li::before{content:"·";
  color:var(--text-3)}.tag-list{display:flex;gap:8px 16px;flex-wrap:wrap;color:var(--text-3);font:11.5px var(--mono)}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:34px}
.three-col{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}.definition-list{display:grid;gap:8px;font-size:12px}
.definition-row{display:flex;justify-content:space-between;gap:14px}.definition-row dt{color:var(--text-3)}
.definition-row dd{margin:0;text-align:right;color:var(--text-2);word-break:break-word}.timeline-list{list-style:none;margin:0;
  padding:0 0 0 8px}.timeline-item{position:relative;padding:0 0 18px 23px;border-left:1px solid var(--border)}
.timeline-item:last-child{border-color:transparent}.timeline-item::before{content:"";position:absolute;left:-5px;top:4px;
  width:9px;height:9px;border-radius:50%;background:var(--surface-2);border:1px solid var(--text-3)}
.timeline-status{font:600 11.5px var(--mono)}.timeline-time{font-size:11px;color:var(--text-3);margin-top:2px}
.timeline-detail{font-size:12px;color:var(--text-2);margin-top:5px}.footer-note{text-align:center;color:var(--text-3);
  font-size:10.5px;padding-top:28px}
@media(max-width:760px){.nav-shell{padding:0 14px;gap:16px}main,main.wide{padding:24px 16px 50px}
  .overview-grid,.operator-grid,.two-col,.three-col{grid-template-columns:1fr}.page-head{align-items:flex-start;flex-direction:column}
  .trace-time{width:100%;margin-left:0}.position-summary{grid-template-columns:minmax(0,1fr) auto}
  .position-summary .position-meta:first-of-type{display:none}.stats{gap:20px}.source summary{grid-template-columns:58px minmax(0,1fr)}
  .source summary .confidence{grid-column:2}.source-detail{padding-left:70px}}
@media(max-width:520px){.brand{font-size:0}.brand-mark{font-size:14px}.live-grid{grid-template-columns:minmax(0,1fr)}
  .position-summary{gap:9px}.position-detail{padding-left:16px}.feed-meta a{width:100%;margin-left:0}
  table{min-width:580px}.trace-step{min-width:82px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""

_NAV = (
    ("Dashboard", "/"),
    ("Paper operator", "/operate"),
    ("Live trial", "/operate/live"),
    ("Portfolio", "/portfolio"),
    ("Decisions", "/decisions"),
    ("Executions", "/executions"),
    ("Digests", "/digests"),
    ("X", "/x"),
    ("Regime", "/regime"),
    ("Triggers", "/triggers"),
)

_SCRIPT = """
document.querySelectorAll('[data-copy]').forEach((button)=>{
  button.addEventListener('click',async()=>{
    const node=document.getElementById(button.dataset.copy);
    if(!node)return;
    await navigator.clipboard.writeText(node.innerText);
    const old=button.innerText;button.innerText='Copied';
    window.setTimeout(()=>button.innerText=old,1200);
  });
});
document.querySelectorAll('[data-tabset]').forEach((tabset)=>{
  const buttons=[...tabset.querySelectorAll('[role="tab"]')];
  buttons.forEach((button,index)=>button.addEventListener('click',()=>{
    buttons.forEach((item)=>{
      const selected=item===button;
      item.setAttribute('aria-selected',String(selected));
      item.tabIndex=selected?0:-1;
      document.getElementById(item.getAttribute('aria-controls')).hidden=!selected;
    });
  }));
  tabset.addEventListener('keydown',(event)=>{
    if(!['ArrowLeft','ArrowRight'].includes(event.key))return;
    const current=buttons.indexOf(document.activeElement);
    const next=(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
    buttons[next].click();buttons[next].focus();event.preventDefault();
  });
});
"""


def page(title: str, body: str, *, active: str = "", eyebrow: str = "", wide: bool = False) -> str:
    links = "".join(
        f"<a href='{href}'{' aria-current=' + chr(39) + 'page' + chr(39) if href == active else ''}>"
        f"{escape(label)}</a>"
        for label, href in _NAV
    )
    page_eyebrow = escape(eyebrow or "Autonomous investment decision harness")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} | BouStrategy</title><style>{_STYLE}</style></head><body>"
        "<a class='skip-link' href='#content'>Skip to content</a>"
        "<header class='site-header'><nav class='nav-shell' aria-label='Primary'>"
        "<a class='brand' href='/'><span class='brand-mark'>B/</span> BouStrategy</a>"
        f"<div class='nav-links'>{links}</div></nav></header>"
        f"<main id='content'{' class=' + chr(39) + 'wide' + chr(39) if wide else ''}>"
        f"<header class='page-head'><div><div class='eyebrow'>{page_eyebrow}</div>"
        f"<h1>{escape(title)}</h1></div></header>{body}"
        "<div class='footer-note'>Private localhost interface · read-only "
        "except supervised paper preparation</div>"
        f"</main><script>{_SCRIPT}</script></body></html>"
    )


def status_badge(value: str) -> str:
    lowered = value.casefold()
    css = "good" if lowered in _STATUS_GOOD else "warn" if lowered in _STATUS_WARN else ""
    css = "bad" if lowered in _STATUS_BAD else css
    label = value.replace("_", " ")
    return f"<span class='status {css}' data-status='{escape(value)}'>{escape(label)}</span>"


def copy_button(target: str, label: str, enabled: bool = True, reason: str = "") -> str:
    disabled = "" if enabled else " disabled"
    explanation = (
        f"<span class='control-note' role='note'>{escape(reason)}</span>"
        if not enabled and reason
        else ""
    )
    return (
        f"<button type='button' data-copy='{escape(target)}'{disabled} title='{escape(reason)}'>"
        f"{escape(label)}</button>{explanation}"
    )


def table(items: list[dict[str, Any]] | None) -> str:
    if items is None:
        return "<p class='empty'>unavailable</p>"
    if not items:
        return "<p class='empty'>none yet</p>"
    headers = list(items[0])
    head = "".join(f"<th scope='col'>{escape(name.replace('_', ' '))}</th>" for name in headers)
    body_rows = []
    for item in items:
        cells = []
        for name in headers:
            value = item.get(name)
            if value is None or value == "":
                rendered = "<span class='empty'>unavailable</span>"
            elif name in {"status", "regime", "raw_regime", "final_status", "rank"}:
                rendered = status_badge(str(value))
            elif isinstance(value, bool):
                rendered = "yes" if value else "no"
            elif isinstance(value, float):
                rendered = f"{value:,.2f}"
            elif isinstance(value, int):
                rendered = f"{value:,}"
            else:
                rendered = escape(str(value))
            css = (
                " class='num'"
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else ""
            )
            cells.append(f"<td{css}>{rendered}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"


def sparkline(values: list[float] | None) -> str:
    if not values:
        return "<p class='empty'>none yet</p>"
    low, high = min(values), max(values)
    spread = high - low or 1
    width = max(len(values) - 1, 1)
    points = [
        (index / width * 600, 100 - (value - low) / spread * 90 - 5)
        for index, value in enumerate(values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"0,100 {line} 600,100"
    return (
        "<figure class='spark'><figcaption><span>Paper equity history</span>"
        f"<span class='mono'>latest ${values[-1]:,.2f}</span></figcaption>"
        "<svg viewBox='0 0 600 108' preserveAspectRatio='none' role='img' "
        "aria-label='Paper account equity over available price history'>"
        f"<polygon class='area' points='{area}'/><polyline class='line' points='{line}'/>"
        "</svg></figure>"
    )


def _position_rows(positions: list[dict[str, Any]] | None) -> str:
    if not positions:
        return "<p class='empty'>none yet · positions appear after eligible paper intents fill</p>"
    rendered = []
    for position in positions:
        pnl = position.get("unrealized_pl")
        pnl_class = "positive" if isinstance(pnl, (int, float)) and pnl >= 0 else "negative"
        latest = position.get("latest_close")
        rendered.append(
            "<details class='position'><summary class='position-summary'>"
            "<span class='position-title'><span class='chevron' aria-hidden='true'></span>"
            f"<span class='ticker'>{escape(str(position['ticker']))}</span>"
            f"<span class='muted'>{escape(str(position.get('primary_theme_id') or 'unclassified'))}</span></span>"
            f"<span class='position-meta'>{position.get('weight', 0):.1%}</span>"
            f"<span class='position-meta {pnl_class}'>{pnl:+,.2f}</span></summary>"
            "<div class='position-detail'><div class='metric-grid'>"
            f"<div><div class='metric-label'>Shares</div><div class='metric-value'>{position['shares']:,.4g}</div></div>"
            f"<div><div class='metric-label'>Average cost</div><div class='metric-value'>${position['avg_cost']:,.2f}</div></div>"
            f"<div><div class='metric-label'>Latest close</div><div class='metric-value'>{f'${latest:,.2f}' if latest is not None else 'unavailable'}</div></div>"
            f"<div><div class='metric-label'>Market value</div><div class='metric-value'>${position.get('value', 0):,.2f}</div></div>"
            f"<div><div class='metric-label'>Portfolio weight</div><div class='metric-value'>{position.get('weight', 0):.2%}</div></div>"
            f"<div><div class='metric-label'>Unrealized P/L</div><div class='metric-value {pnl_class}'>{pnl:+,.2f}</div></div>"
            "</div></div></details>"
        )
    return "".join(rendered)


def _decision_feed(items: list[dict[str, Any]] | None, *, limit: int | None = None) -> str:
    if not items:
        return "<p class='empty'>none yet · completed reasoning decisions will appear here</p>"
    rendered = []
    for item in items[:limit] if limit else items:
        summary = item.get("public_summary") or "No public summary was recorded."
        outcome = item.get("final_status") or "unavailable"
        metadata = []
        if item.get("primary_theme"):
            metadata.append(escape(str(item["primary_theme"])))
        if item.get("target_weight") is not None:
            metadata.append(f"target {item['target_weight']:.1%}")
        rendered.append(
            "<article class='feed-item'><div class='feed-head'><div class='feed-title'>"
            f"<span class='ticker'>{escape(str(item['ticker']))}</span>"
            f"<strong>{escape(str(item['decision']).title())}</strong></div>"
            f"<time class='feed-time'>{escape(str(item['created_at']))}</time></div>"
            f"<div class='feed-summary'>{escape(str(summary))}</div><div class='feed-meta'>"
            f"{status_badge(str(outcome))}{status_badge(str(item.get('regime') or 'unavailable'))}"
            f"<span class='quiet'>{' · '.join(metadata) if metadata else 'recorded decision'}</span>"
            f"<a href='/decisions/{escape(str(item['decision_id']))}'>View full trace →</a>"
            "</div></article>"
        )
    return "".join(rendered)


def dashboard(payload: dict[str, Any]) -> str:
    paper = payload.get("paper")
    statuses: dict[str, int] = payload.get("policy_outcomes") or {}
    positions = payload.get("positions")
    deployed = sum(position.get("value", 0) for position in positions or [])
    if paper:
        delta = paper["equity"] - paper["starting"]
        stats = (
            f"<div><div class='stat-value'>${paper['equity']:,.2f}</div><div class='stat-label'>Paper equity</div></div>"
            f"<div><div class='stat-value'>${paper['cash']:,.2f}</div><div class='stat-label'>Cash</div></div>"
            f"<div><div class='stat-value {'positive' if delta >= 0 else 'negative'}'>{delta:+,.2f}</div><div class='stat-label'>Since start</div></div>"
            f"<div><div class='stat-value'>{len(positions or []):,}</div><div class='stat-label'>Positions</div></div>"
        )
    else:
        stats = "".join(
            f"<div><div class='stat-value'>—</div><div class='stat-label'>{label}</div></div>"
            for label in ("Paper equity", "Cash", "Since start", "Positions")
        )
    operational = payload.get("operational") or {}
    policy_rows = (
        "".join(
            f"<div class='compact-row'><span>{escape(status.replace('_', ' '))}</span>"
            f"<strong class='mono'>{count:,}</strong></div>"
            for status, count in sorted(statuses.items())
        )
        if statuses
        else "<p class='empty'>none yet · policy outcomes are shown after "
        "decisions pass the pipeline</p>"
    )
    regime = payload.get("regime")
    regime_value = status_badge(regime["regime"]) if regime else status_badge("unavailable")
    return (
        "<div class='mode-strip'><strong>Paper account</strong><span>Live "
        "state stays isolated in the Live operator and Executions "
        "views.</span></div>"
        f"<div class='stats'>{stats}</div>"
        "<div class='tabs' aria-label='Dashboard sections'><a class='active' href='#feed'>Feed</a>"
        "<a href='#positions'>Positions</a><a href='#policy'>Policy</a><a "
        "href='#operations'>Operations</a></div>"
        "<section class='section' id='feed'><div class='section-label'>Recent decisions</div>"
        f"{_decision_feed(payload.get('recent_decisions'))}</section>"
        "<section class='section' id='positions'><div class='split'><div "
        "class='section-label'>Paper positions</div>"
        f"<span class='quiet mono'>deployed ${deployed:,.2f}</span></div>{_position_rows(positions)}</section>"
        "<div class='overview-grid'><section class='section' "
        "id='policy'><div class='section-label'>Recorded policy "
        "outcomes</div>"
        f"{policy_rows}</section><section class='section' id='operations'><div class='section-label'>Market and operations</div>"
        f"<div class='compact-list'><div class='compact-row'><span>Regime</span>{regime_value}</div>"
        f"<div class='compact-row'><span>Pending triggers</span><strong class='mono'>{payload.get('pending_triggers', 'unavailable')}</strong></div>"
        f"<div class='compact-row'><span>Latest digest</span><strong>{escape(str(payload.get('last_digest') or 'unavailable'))}</strong></div>"
        + "".join(
            f"<div class='compact-row'><span>{escape(name.replace('_', ' '))}</span>{status_badge(str(value))}</div>"
            for name, value in operational.items()
            if name not in {"regime", "paper_portfolio"}
        )
        + "</div></section></div>"
    )


def portfolio(payload: dict[str, Any]) -> str:
    return (
        "<div class='mode-strip'><strong>Paper "
        "portfolio</strong><span>Prices are the latest persisted daily "
        "closes. Pending intents aren't treated as positions.</span></div>"
        "<section class='section'><div class='section-label'>Equity</div>"
        f"{sparkline(payload['equity_series'])}</section>"
        "<section class='section'><div class='section-label'>Positions</div>"
        f"{_position_rows(payload['positions'])}</section>"
        "<section class='section'><div class='section-label'>Order intents</div>"
        f"{table(payload['intents'])}</section>"
        "<section class='section'><div class='section-label'>Paper fills</div>"
        f"{table(payload['fills'])}</section>"
    )


def decisions(items: list[dict[str, Any]] | None) -> str:
    return (
        "<div class='mode-strip'><strong>Immutable "
        "records</strong><span>Each item links to its stored thesis, "
        "validation, policy, intent, and execution trace.</span></div>"
        f"<section aria-label='Decision feed'>{_decision_feed(items)}</section>"
    )


def _criteria(items: list[str] | None, empty_text: str = "none recorded") -> str:
    if not items:
        return f"<p class='empty'>{escape(empty_text)}</p>"
    return (
        "<ul class='criteria'>"
        + "".join(f"<li>{escape(str(item))}</li>" for item in items)
        + "</ul>"
    )


def _definition_list(items: list[tuple[str, Any]]) -> str:
    rows = []
    for label, value in items:
        rendered = "unavailable" if value is None or value == "" else str(value)
        rows.append(
            f"<div class='definition-row'><dt>{escape(label)}</dt><dd>{escape(rendered)}</dd></div>"
        )
    return f"<dl class='definition-list'>{''.join(rows)}</dl>"


def decision_trace(payload: dict[str, Any]) -> str:
    record = payload["record"]
    ticker = record.get("ticker", "unavailable")
    decision = record.get("decision", "unavailable")
    summary = record.get("public_summary") or "No public summary was recorded."
    chain = [
        ("Initial", record.get("initial_thesis")),
        ("Counter", record.get("counter_thesis")),
        ("Refine", record.get("adversarial_refinement")),
        ("Final", record.get("refined_thesis")),
        ("Priced in", record.get("what_is_priced_in")),
    ]
    tabs = []
    panels = []
    for index, (label, text) in enumerate(chain):
        panel_id = f"thesis-stage-{index}"
        selected = index == 0
        panel_text = escape(str(text)) if text else "<span class='empty'>not recorded</span>"
        tabs.append(
            f"<button class='trace-step' role='tab' aria-selected='{str(selected).lower()}' "
            f"aria-controls='{panel_id}' tabindex='{'0' if selected else '-1'}'>{escape(label)}</button>"
        )
        panels.append(
            f"<div class='trace-panel' id='{panel_id}' role='tabpanel'{' hidden' if not selected else ''}>"
            f"{panel_text}</div>"
        )

    sources = []
    for claim in record.get("source_claims") or []:
        confidence = claim.get("confidence")
        confidence_label = (
            f"{confidence:.0%}" if isinstance(confidence, (float, int)) else "unavailable"
        )
        source_ids = ", ".join(str(source_id) for source_id in claim.get("source_ids") or [])
        sources.append(
            "<details class='source'><summary>"
            f"<span class='source-type'>{escape(str(claim.get('source_type', 'unknown')))}</span>"
            f"<span>{escape(str(claim.get('claim', 'No claim recorded.')))}</span>"
            f"<span class='confidence'>{confidence_label}</span></summary>"
            f"<div class='source-detail'>IDs: {escape(source_ids or 'unavailable')} · "
            f"{escape(str(claim.get('source_timestamp', 'timestamp unavailable')))} · "
            f"public safe: {'yes' if claim.get('public_safe') else 'no'}</div></details>"
        )
    sources_html = "".join(sources) if sources else "<p class='empty'>none recorded</p>"

    trigger = payload.get("trigger")
    if trigger:
        trigger_detail = _definition_list(
            [
                ("Type", trigger["trigger_type"]),
                ("Subject", trigger["subject"]),
                ("Fired", trigger["fired_at"]),
                ("Status", trigger["status"]),
                ("Evidence", trigger["details"]),
            ]
        )
    elif record.get("trigger_id"):
        trigger_detail = f"<p class='empty'>trigger {escape(str(record['trigger_id']))} is referenced but its persisted event is unavailable</p>"
    else:
        trigger_detail = "<p class='empty'>no trigger linked</p>"

    tags = [*(record.get("strategy_belief_ids") or []), *(record.get("theme_ids") or [])]
    tags_html = (
        "<div class='tag-list'>"
        + "".join(f"<span>{escape(str(tag))}</span>" for tag in tags)
        + "</div>"
        if tags
        else "<p class='empty'>none recorded</p>"
    )
    strategy_frame = _definition_list(
        [
            ("Asset type", record.get("asset_type")),
            ("Operating mode", record.get("operating_mode")),
            ("Primary theme", record.get("primary_theme_id")),
            (
                "Extraordinary opportunity",
                "yes" if record.get("extraordinary_opportunity") else "no",
            ),
            ("Source pack", record.get("source_pack_id")),
        ]
    )
    if record.get("extraordinary_opportunity"):
        strategy_frame += (
            "<div class='feed-summary' style='margin-top:12px'>"
            f"{escape(str(record.get('extraordinary_justification') or 'No justification recorded.'))}"
            "</div>"
        )
    regime = payload.get("regime_evidence")
    regime_html = (
        _definition_list(
            [
                ("Published state", regime["regime"]),
                ("Raw state", regime["raw_regime"]),
                ("Score", regime["score"]),
                ("Snapshot", regime["snapshot_date"]),
                ("Computed", regime["computed_at"]),
                ("Components", regime["components"]),
            ]
        )
        if regime
        else "<p class='empty'>published regime evidence unavailable for this decision date</p>"
    )

    intent = payload.get("intent")
    intent_html = (
        _definition_list(
            [
                ("Order intent", intent["order_intent_id"]),
                ("Mode", intent["execution_mode"]),
                ("Profile", intent["execution_profile_id"] or "paper"),
                ("Side", intent["side"]),
                ("Order type", intent["order_type"]),
                (
                    "Target weight",
                    f"{intent['target_weight']:.2%}"
                    if intent["target_weight"] is not None
                    else None,
                ),
                ("Status", intent["status"]),
            ]
        )
        if intent
        else "<p class='empty'>no order intent created</p>"
    )

    validation_html = _definition_list(
        [
            ("Schema", payload["schema_result"]),
            ("Policy", payload["policy_result"]),
            ("Final pipeline state", payload["final_status"]),
        ]
    )
    if payload["policy_reasons"]:
        validation_html += (
            "<div class='section-label' style='margin-top:14px'>Rejection reasons</div>"
            + _criteria(payload["policy_reasons"])
        )

    x_usage = record.get("x_signal_usage") or {}
    x_html = _definition_list(
        [
            ("Used", "yes" if x_usage.get("used") else "no"),
            ("Usage", x_usage.get("usage_type")),
            ("Outside-X confirmation", "yes" if x_usage.get("confirmed_outside_x") else "no"),
            ("Summary", x_usage.get("summary") or "none recorded"),
        ]
    )

    timeline: list[tuple[str, str, str]] = []
    run = payload.get("reasoning_run")
    if run:
        timeline.append(
            (
                "reasoning_started",
                run["started_at"],
                f"{run['model_label']} · {run['reasoning_run_id']}",
            )
        )
    timeline.extend(
        (
            event["status"],
            event["occurred_at"],
            event["detail"] or "Recorded by the decision pipeline.",
        )
        for event in payload["status_events"]
    )
    if intent:
        timeline.append(
            (
                "intent_persisted",
                intent["created_at"],
                f"{intent['execution_mode']} · {intent['order_intent_id']}",
            )
        )
    timeline.extend(
        (
            "packet_created",
            packet["created_at"],
            f"{packet['execution_packet_id']} · expires {packet['expires_at']}",
        )
        for packet in payload["packets"]
    )
    timeline.extend(
        (event["status"], event["occurred_at"], "Broker lifecycle event persisted.")
        for event in payload["execution_events"]
    )
    if run and run.get("completed_at"):
        timeline.append((run["result"], run["completed_at"], "Reasoning run completed."))
    timeline.sort(key=lambda item: item[1] or "")
    timeline_tabs = []
    timeline_panels = []
    for index, (status, occurred_at, detail) in enumerate(timeline):
        panel_id = f"pipeline-event-{index}"
        selected = index == len(timeline) - 1
        timeline_tabs.append(
            f"<button class='trace-step' role='tab' aria-selected='{str(selected).lower()}' "
            f"aria-controls='{panel_id}' tabindex='{'0' if selected else '-1'}'>"
            f"{escape(status.replace('_', ' '))}</button>"
        )
        timeline_panels.append(
            f"<div class='trace-panel' id='{panel_id}' role='tabpanel'"
            f"{' hidden' if not selected else ''}><div class='timeline-time'>"
            f"{escape(str(occurred_at))}</div><div class='timeline-detail'>{escape(str(detail))}"
            "</div></div>"
        )
    timeline_html = (
        f"<div class='pipeline-rail' role='tablist' aria-label='Pipeline events'>{''.join(timeline_tabs)}</div>"
        + "".join(timeline_panels)
        if timeline
        else "<p class='empty'>pipeline events unavailable</p>"
    )

    packet_html = table(payload["packets"])
    execution_html = table(payload["executions"])
    if not payload["packets"]:
        packet_html = "<p class='empty'>no live execution packet</p>"
    if not payload["executions"]:
        execution_html = "<p class='empty'>no persisted broker execution record</p>"

    return (
        "<a class='back-link' href='/decisions'>← Decision feed</a>"
        "<article><header class='trace-head'><div class='trace-title'>"
        f"<span class='ticker' style='font-size:19px'>{escape(str(ticker))}</span>"
        f"{status_badge(str(decision))}{status_badge(str(record.get('regime_state') or 'unavailable'))}"
        f"{status_badge(str(payload['final_status']))}"
        f"<time class='trace-time'>{escape(str(record.get('created_at', 'time unavailable')))}</time>"
        f"</div><p class='lede' style='margin-top:10px'>{escape(str(summary))}</p></header>"
        "<div class='thesis-callout'><span class='thesis-dot' aria-hidden='true'></span><div>"
        "<div class='section-label' style='margin-bottom:4px'>Refined thesis</div>"
        f"<div class='thesis-text'>{escape(str(record.get('refined_thesis') or 'not recorded'))}</div></div></div>"
        "<section class='section' data-tabset><div "
        "class='section-label'>Recorded thesis chain</div>"
        f"<div class='trace-rail' role='tablist' aria-label='Thesis stages'>{''.join(tabs)}</div>{''.join(panels)}"
        f"<p class='quiet' style='margin-top:12px'>Proposed {record.get('proposed_target_weight', 0):.2%} · final {record.get('final_target_weight', 0):.2%}</p></section>"
        f"<section class='section'><div class='section-label'>Trigger</div>{trigger_detail}</section>"
        f"<section class='section'><div class='section-label'>Source pack · {len(sources)} claims</div>{sources_html}</section>"
        "<div class='two-col'><section class='section'><div "
        "class='section-label'>Invalidation criteria</div>"
        f"{_criteria(record.get('thesis_invalidation_criteria'))}</section>"
        "<section class='section'><div class='section-label'>Strategy beliefs and themes</div>"
        f"{strategy_frame}<div style='margin-top:14px'>{tags_html}</div></section></div>"
        "<section class='section'><details><summary "
        "class='section-label'>Portfolio management conditions</summary>"
        "<div class='three-col' style='padding:10px 0 14px'>"
        f"<div><div class='section-label'>Add</div>{_criteria(record.get('add_conditions'))}</div>"
        f"<div><div class='section-label'>Trim</div>{_criteria(record.get('trim_conditions'))}</div>"
        f"<div><div class='section-label'>Exit</div>{_criteria(record.get('exit_conditions'))}</div>"
        "</div></details></section>"
        f"<section class='section'><details><summary class='section-label'>Regime evidence · {escape(str(record.get('regime_state') or 'unavailable'))}</summary><div style='padding:8px 0 14px'>{regime_html}</div></details></section>"
        "<div class='two-col'><section class='section'><div "
        "class='section-label'>Schema and policy</div>"
        f"{validation_html}</section><section class='section'><div class='section-label'>Intent linkage</div>{intent_html}</section></div>"
        f"<section class='section'><div class='section-label'>X signal usage</div>{x_html}</section>"
        "<section class='section'><div class='section-label'>Persisted execution lifecycle</div>"
        f"<div class='quiet'>Packets</div>{packet_html}<div class='quiet'>Broker records</div>"
        f"{execution_html}</section>"
        f"<section class='section'><details open data-tabset><summary class='section-label'>Pipeline timeline · {len(timeline)} events</summary><div style='padding-top:15px'>{timeline_html}</div></details></section>"
        "</article>"
    )


def live_reasoning_prompt(profile: dict[str, Any], shared: dict[str, Any]) -> str:
    run = profile["run"]
    return (
        f"Follow docs/reasoning/RUNBOOK.md for reasoning run {run['reasoning_run_id']} and "
        f"execution profile {profile['execution_profile_id']}. Read shared bundle "
        f"{shared['shared_bundle_path']} with SHA-256 {shared['shared_bundle_sha256']} and only "
        f"initial portfolio snapshot {run['portfolio_snapshot_id']}. Market and research inputs "
        "match the other agent, but account state is intentionally isolated. Don't read or act "
        "on the other profile. Immediately before submitting a decision, capture and save a fresh "
        "snapshot for this same profile and pass its ID as --portfolio-snapshot. Submit every "
        "decision through the live run boundary, then complete the run with a public summary, "
        "including when the result is no action."
    )


def live_execution_prompt(execution_profile_id: str, execution_packet_id: str) -> str:
    return (
        f"Follow docs/execution/EXECUTOR.md for exactly one packet {execution_packet_id} assigned "
        f"to execution profile {execution_profile_id}. Verify and reconcile only that current "
        "packet. Don't research, resize, substitute accounts, or continue to another packet. "
        "Stop after one reconciled packet."
    )


def live_operator(payload: dict[str, Any], *, now: datetime) -> str:
    shared = payload["shared"]
    shared_html = (
        "<div class='panel'><div class='section-label'>Shared intake</div>"
        f"<div class='split'><strong>{escape(shared['session_date'])} · {escape(shared['slot'])}</strong>"
        f"{status_badge('available')}</div><p class='mono' style='margin-top:8px'>{escape(shared['shared_bundle_path'])}</p>"
        f"<p class='quiet mono' style='margin-top:6px'>SHA-256 {escape(shared['shared_bundle_sha256'])}</p></div>"
        if shared
        else "<div class='panel'><div class='section-label'>Shared "
        "intake</div><div class='error'>none yet · No prepared live "
        "reasoning runs. Save the profile snapshot, then prepare the "
        "shared bundle with the live reasoning CLI.</div></div>"
    )
    cards = []
    comparison = []
    for profile in payload["profiles"]:
        snapshot = profile["snapshot"]
        run = profile["run"]
        displayed_run_status = profile.get("runtime_status") or (
            run["result"] if run else "unavailable"
        )
        age = "unavailable"
        if snapshot:
            seconds = max(
                0, int((now - datetime.fromisoformat(snapshot["captured_at"])).total_seconds())
            )
            age = f"{seconds}s"
        if profile["enabled"] and profile["account_bound"] and profile["supported"]:
            readiness = "ready"
            profile_state = "account bound and enabled"
        elif profile["account_bound"] and snapshot and profile["supported"]:
            readiness = "pending"
            profile_state = "ready to enable; account bound and snapshot saved; profile disabled"
        elif not profile["supported"]:
            readiness = "unavailable"
            profile_state = "Claude is disabled future support"
        else:
            readiness = "missing"
            profile_state = "profile disabled, account not bound, or snapshot missing"
        profile_id = str(profile["execution_profile_id"])
        equity = f"${snapshot['account_equity']:,.2f}" if snapshot else "unavailable"
        buying_power = f"${snapshot['buying_power']:,.2f}" if snapshot else "unavailable"
        reasoning_text = (
            live_reasoning_prompt(profile, shared)
            if profile["reasoning_ready"]
            else "Reasoning isn't ready."
        )
        execution_text = (
            live_execution_prompt(profile_id, profile["execution_packet_id"])
            if profile["execution_ready"]
            else "Execution isn't ready."
        )
        cards.append(
            "<section class='panel'><div class='split'><div><div "
            "class='section-label'>Execution profile</div>"
            f"<h2><span class='mono'>{escape(profile_id)}</span> · {escape(str(profile['agent_provider']))}</h2></div>"
            f"{status_badge(readiness)}</div><p style='margin-top:8px'>{escape(profile_state)}</p>"
            "<div class='metric-grid' style='margin-top:16px'>"
            f"<div><div class='metric-label'>Snapshot age</div><div class='metric-value'>{escape(age)}</div></div>"
            f"<div><div class='metric-label'>Equity</div><div class='metric-value'>{equity}</div></div>"
            f"<div><div class='metric-label'>Buying power</div><div class='metric-value'>{buying_power}</div></div>"
            f"<div><div class='metric-label'>Positions</div><div class='metric-value'>{len(snapshot['positions']) if snapshot else 0}</div></div>"
            f"<div><div class='metric-label'>Run</div><div class='metric-value'>{escape(displayed_run_status)}</div></div>"
            f"<div><div class='metric-label'>Decisions</div><div class='metric-value'>{run['decision_count'] if run else 0}</div></div>"
            f"<div><div class='metric-label'>Pending packets</div><div class='metric-value'>{profile['pending_packet_count']}</div></div>"
            f"<div><div class='metric-label'>Lifecycle</div><div class='metric-value'>{escape(profile['execution_status'] or 'unavailable')}</div></div>"
            "</div>"
            + (
                f"<p style='margin-top:14px'>Run summary: {escape(run['public_summary'] or 'none yet')}</p>"
                if run
                else "<p style='margin-top:14px'>Run summary: none yet</p>"
            )
            + (
                f"<div class='error'>{escape(profile['execution_error'])}</div>"
                if profile["execution_error"]
                else ""
            )
            + "<div class='section-label'>Actual runtime attempts</div>"
            + table(profile.get("runtime_attempts", []))
            + f"<div class='section-label' style='margin-top:18px'>Reasoning handoff</div><pre class='prompt' id='reasoning-{escape(profile_id)}'>{escape(reasoning_text)}</pre>"
            + copy_button(
                f"reasoning-{profile_id}",
                "Copy reasoning prompt",
                profile["reasoning_ready"],
                profile["reasoning_unavailable"],
            )
            + f"<div class='section-label' style='margin-top:18px'>Execution handoff</div><pre class='prompt' id='execution-{escape(profile_id)}'>{escape(execution_text)}</pre>"
            + copy_button(
                f"execution-{profile_id}",
                "Copy execution prompt",
                profile["execution_ready"],
                profile["execution_unavailable"],
            )
            + "</section>"
        )
        comparison.append(
            {
                "profile": profile_id,
                "provider": profile["agent_provider"],
                "enabled": profile["enabled"] and profile["supported"],
                "equity": snapshot["account_equity"] if snapshot else None,
                "run": displayed_run_status,
                "decisions": run["decision_count"] if run else 0,
                "pending_packets": profile["pending_packet_count"],
            }
        )
    profiles_html = (
        "".join(cards)
        if cards
        else "<div class='panel'><p class='empty'>no live profiles configured</p></div>"
    )
    return (
        "<div class='mode-strip'><strong>Live "
        "operator</strong><span>Private profile state. Prompts are copied "
        "for separate sessions; this page never contacts a "
        "broker.</span></div>"
        f"{shared_html}<div class='live-grid'>{profiles_html}</div>"
        f"<section class='section'><div class='section-label'>Profile status</div>{table(comparison)}</section>"
    )


def paper_operator(
    status: dict[str, Any], csrf_token: str, slot: str, *, notice: str = "", error: str = ""
) -> str:
    day = str(status["date"])
    digester_prompt = (
        f"Follow docs/x_pipeline/DIGESTER.md for {day} using the {slot} slot. This is a supervised "
        "manual run. Stop after the digest is rendered and verified. Don't "
        "continue into investment reasoning."
    )
    reasoning_prompt = (
        f"Follow docs/reasoning/RUNBOOK.md for {day} using data/reason_runs/{day}/bundle.md and its "
        f"preparation.json receipt. This is the {slot} paper reasoning pass. First review existing "
        "positions, pending order intents, prior same-day decisions, and "
        "the remaining daily quota. "
        "Don't resubmit an existing decision record or treat a pending "
        "intent as a filled position. "
        "Then select the 2-3 strongest eligible U.S.-listed candidates and actively research "
        "independent primary or reputable sources plus current price context before applying the "
        "complete thesis chain. Treat missing outside-X confirmation as a research task, not an "
        "automatic reason to reject a candidate. Give each new record the "
        "actual current timestamp, "
        "never a future timestamp, and submit it exactly once. Append a "
        "distinct timestamped section "
        "for this pass to the reasoning-session log even if none survives "
        "the research and the correct "
        "result is no action. Don't force a trade. Show me every new "
        "decision record and submission result."
    )
    runs = status["runs"]
    run_summary = (
        ", ".join(f"{run['slot']}: {run['status']}" for run in runs) if runs else "none recorded"
    )
    receipt = status["receipt"] or {}
    receipt_summary = (
        f"{receipt.get('fills_created', 0)} fills, {receipt.get('intents_awaiting_price', 0)} awaiting, regime {receipt.get('regime', 'unknown')}"
        if receipt
        else "not prepared"
    )
    slot_options = "".join(
        f"<option value='{item}'{' selected' if item == slot else ''}>{item}</option>"
        for item in ("close", "midday", "morning")
    )
    return (
        "<div class='mode-strip'><strong>Paper "
        "operator</strong><span>Supervised preparation only. It doesn't "
        "contact a broker.</span></div>"
        "<div class='operator-grid'><section>"
        "<div class='panel'><div class='step'><div "
        "class='step-number'>1</div><div><h2>Digest the feed</h2>"
        "<p>Copy this into a fresh agent session. Nothing runs or spends X "
        "credits until you start that separate session.</p>"
        f"<pre class='prompt' id='digester-prompt'>{escape(digester_prompt)}</pre>{copy_button('digester-prompt', 'Copy digester prompt')}</div></div></div>"
        "<div class='panel'><div class='step'><div "
        "class='step-number'>2</div><div><h2>Prepare the paper session</h2>"
        "<p>Refresh market and calendar data, settle eligible paper "
        "intents, evaluate triggers, score the regime, and create the "
        "intake receipt.</p>"
        + (f"<div class='notice'>{escape(notice)}</div>" if notice else "")
        + (f"<div class='error'>{escape(error)}</div>" if error else "")
        + f"<form method='post' action='/operate/prepare'><input type='hidden' name='csrf_token' value='{escape(csrf_token)}'>"
        f"<input type='hidden' name='date' value='{escape(day)}'><input type='hidden' name='slot' value='{escape(slot)}'>"
        f"<button type='submit'{' disabled' if not status['digest_ready'] else ''}>Prepare paper session</button></form>"
        f"<span class='control-note'>{'Ready. Market data may take a minute to refresh.' if status['digest_ready'] else 'Complete and render the same-day digest first.'}</span>"
        "</div></div></div>"
        "<div class='panel'><div class='step'><div "
        "class='step-number'>3</div><div><h2>Run investment reasoning</h2>"
        "<p>Use a fresh agent only after preparation succeeds.</p>"
        f"<pre class='prompt' id='reasoning-prompt'>{escape(reasoning_prompt)}</pre>"
        f"{copy_button('reasoning-prompt', 'Copy reasoning prompt', status['prepared'], 'Prepare this paper session first.')}</div></div></div>"
        "</section><aside><div class='panel'><div class='section-label'>Session controls</div>"
        f"<form method='get' action='/operate'><div class='controls'><label>Date<input type='date' name='date' value='{escape(day)}'></label>"
        f"<label>Slot<select name='slot'>{slot_options}</select></label><button type='submit' class='secondary'>Load</button></div></form></div>"
        "<div class='panel'><div class='section-label'>Readiness</div><div class='status-list'>"
        f"<div class='status-row'><span>Digest file</span>{status_badge('ready' if status['digest_exists'] else 'missing')}</div>"
        f"<div class='status-row'><span>Database runs</span><strong>{escape(run_summary)}</strong></div>"
        f"<div class='status-row'><span>Preparation</span>{status_badge('ready' if status['prepared'] else 'pending')}</div>"
        f"<div class='status-row'><span>Receipt</span><strong>{escape(receipt_summary)}</strong></div></div></div>"
        "<div class='panel'><div class='section-label'>Safety "
        "boundary</div><p>Paper only. Scheduled tasks remain disabled. The "
        "dashboard has no live-broker connection and can't enable "
        "one.</p></div>"
        "</aside></div>"
    )


def executions(
    profiles: list[dict[str, object]] | None,
    packets: list[dict[str, Any]] | None,
    handoffs: list[dict[str, Any]],
    records: list[dict[str, Any]] | None,
    events: list[dict[str, Any]] | None,
) -> str:
    prompts = []
    prompt_handoffs = [handoff for handoff in handoffs if handoff["ready"]] or handoffs[:1]
    if prompt_handoffs:
        for index, handoff in enumerate(prompt_handoffs):
            prompt_id = "execution-prompt" if index == 0 else f"execution-prompt-{index}"
            text = (
                live_execution_prompt(
                    handoff["execution_profile_id"], handoff["execution_packet_id"]
                )
                if handoff["ready"]
                else "Execution isn't ready."
            )
            prompts.append(
                "<div class='panel'>"
                f"<div class='split'><strong class='mono'>{escape(str(handoff['execution_packet_id']))}</strong>"
                f"{status_badge('ready' if handoff['ready'] else 'unavailable')}</div>"
                f"<pre class='prompt' id='{prompt_id}'>{escape(text)}</pre>"
                f"{copy_button(prompt_id, 'Copy execution prompt', handoff['ready'], handoff['unavailable'])}</div>"
            )
    else:
        prompts.append(
            "<div class='panel'><pre class='prompt' "
            "id='execution-prompt'>Execution isn't ready.</pre>"
            + copy_button(
                "execution-prompt",
                "Copy execution prompt",
                False,
                "No execution packet is available.",
            )
            + "</div>"
        )
    return (
        "<div class='mode-strip'><strong>Append-only "
        "ledger</strong><span>Dashboard placement is disabled. This is a "
        "broker lifecycle record and prompt handoff, never an order-entry "
        "screen.</span></div>"
        f"<section class='section'><div class='section-label'>Execution profiles</div>{table(profiles)}</section>"
        f"<section class='section'><div class='section-label'>Execution packets</div>{table(packets)}</section>"
        f"<section class='section'><div class='section-label'>Execution-only handoff</div>{''.join(prompts)}</section>"
        f"<section class='section'><div class='section-label'>Execution records</div>{table(records)}</section>"
        f"<section class='section'><div class='section-label'>Lifecycle events</div>{table(events)}</section>"
    )


def regime_table(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return table(items)
    rows = []
    for index, item in enumerate(items):
        older = items[index + 1]["regime"] if index + 1 < len(items) else None
        rows.append({**item, "state_change": item["regime"] != older})
    return table(rows)
