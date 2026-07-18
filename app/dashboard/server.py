import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.dashboard import queries
from app.storage.database import connect


def render_x_snippet(text: str, public: bool = False) -> str:
    """Single future public-mode seam: public surfaces must use claim summaries."""
    return "[private snippet hidden]" if public else text[:280]


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + escape(title)
        + "</title><style>body{font-family:system-ui;max-width:1200px;margin:2rem auto}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #ccc;"
        "padding:.4rem;text-align:left}pre{white-space:pre-wrap}nav a{margin-right:1rem}</style>"
        "</head><body><nav><a href='/'>Overview</a><a href='/portfolio'>Portfolio</a>"
        "<a href='/decisions'>Decisions</a><a href='/digests'>Digests</a>"
        "<a href='/x'>X</a><a href='/regime'>Regime</a><a href='/triggers'>Triggers</a>"
        f"</nav><h1>{escape(title)}</h1>{body}</body></html>"
    )


def _table(items: list[dict[str, Any]] | None) -> str:
    if items is None:
        return ""
    if not items:
        return "<p>none yet</p>"
    headers = list(items[0])
    head = "".join(f"<th>{escape(name)}</th>" for name in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(item[name]))}</td>" for name in headers) + "</tr>"
        for item in items
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _sparkline(values: list[float] | None) -> str:
    if not values:
        return "<p>none yet</p>"
    low, high = min(values), max(values)
    spread = high - low or 1
    width = max(len(values) - 1, 1)
    points = " ".join(
        f"{index / width * 300:.1f},{100 - (value - low) / spread * 100:.1f}"
        for index, value in enumerate(values)
    )
    return (
        "<svg viewBox='0 0 300 100' role='img'>"
        f"<polyline points='{points}' fill='none' stroke='blue'/></svg>"
    )


def _regime_table(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return _table(items)
    rows = []
    for index, item in enumerate(items):
        older_regime = items[index + 1]["regime"] if index + 1 < len(items) else None
        css = " class='state-change'" if item["regime"] != older_regime else ""
        cells = "".join(f"<td>{escape(str(value))}</td>" for value in item.values())
        rows.append(f"<tr{css}>{cells}</tr>")
    headers = "".join(f"<th>{escape(name)}</th>" for name in items[0])
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="BouStrategy dashboard")
    path = Path(db_path)
    digest_dir = path.parent / "digests"

    @app.get("/", response_class=HTMLResponse)
    def overview() -> str:
        conn = connect(path)
        payload = queries.overview(conn, digest_dir)
        links = {
            "paper": "/portfolio",
            "regime": "/regime",
            "pending_triggers": "/triggers",
            "pending_articles": "/x",
            "last_digest": "/digests",
            "decision_statuses": "/decisions",
            "x_reads": "/x",
        }
        tiles = "".join(
            f"<a class='tile' href='{links[key]}'><strong>{escape(key)}</strong>"
            f"<pre>{escape(json.dumps(value, indent=2))}</pre></a>"
            for key, value in payload.items()
        )
        return _page("Overview", tiles)

    @app.get("/portfolio", response_class=HTMLResponse)
    def portfolio() -> str:
        conn = connect(path)
        payload = queries.portfolio(conn)
        return _page(
            "Portfolio",
            _sparkline(payload["equity_series"])
            + _table(payload["positions"])
            + _table(payload["fills"]),
        )

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions() -> str:
        conn = connect(path)
        return _page("Decisions", _table(queries.decisions(conn)))

    @app.get("/digests", response_class=HTMLResponse)
    def digests(file: str | None = None) -> str:
        if file is not None:
            selected = digest_dir / Path(file).name
            if not selected.exists():
                raise HTTPException(404, "digest not found")
            return _page(file, f"<pre>{escape(selected.read_text(encoding='utf-8'))}</pre>")
        items = (
            [{"file": item.name} for item in sorted(digest_dir.glob("*.md"), reverse=True)]
            if digest_dir.exists()
            else []
        )
        return _page("Digests", _table(items))

    @app.get("/x", response_class=HTMLResponse)
    def x_page() -> str:
        conn = connect(path)
        payload = queries.x_data(conn)
        return _page("X", "".join(_table(value) for value in payload.values()))

    @app.get("/regime", response_class=HTMLResponse)
    def regime() -> str:
        conn = connect(path)
        return _page("Regime", _regime_table(queries.regime(conn)))

    @app.get("/triggers", response_class=HTMLResponse)
    def triggers() -> str:
        conn = connect(path)
        return _page("Triggers", _table(queries.triggers(conn)))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.dashboard.server")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--port", type=int, default=8378)
    args = parser.parse_args()
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
