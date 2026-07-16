"""Local labeling inbox: one post at a time, skip/capture as button clicks.

Thin skin over app/x/posts.py and app/x/signals.py — no new business logic
lives here beyond rendering and request/response shaping.
"""

import argparse
import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.labeling.adjudication import adjudicate, next_payload
from app.storage.database import connect
from app.x.posts import (
    MAX_MONTHLY_POST_READS,
    mark_reviewed,
    reads_remaining,
    unreviewed_posts,
    unreviewed_thread_posts,
)
from app.x.signals import (
    CapturedSignal,
    ClaimType,
    Horizon,
    ScrutinyVerdict,
    Stance,
    save_signal,
)

# Fixed theme button set for the UI only; the schema field (primary_theme_id)
# stays a free string. Buttons remove the typo risk without changing the model.
THEMES = [
    "ai_semiconductors",
    "ai_infrastructure",
    "ai_bottlenecks",
    "data_centers",
    "power_grid_electrification",
    "financial_technology",
    "cloud_hyperscalers",
    "networking_interconnect",
    "robotics_automation",
    "cybersecurity",
    "ai_software",
    "broad_risk_on_tech",
    "macro_liquidity",
    "emergent_theme",
]


class SkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str
    thread_post_ids: list[str] = Field(default_factory=list)


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=1)
    thread_post_ids: list[str] = Field(default_factory=list)
    primary_theme_id: str
    tickers: list[str] = Field(default_factory=list)
    claim: str
    claim_type: ClaimType
    stance: Stance
    horizon: Horizon
    scrutiny_verdict: ScrutinyVerdict
    why_it_matters: str


class AdjudicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predictor: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    verdict: str
    note: str = ""


def _next_payload(conn: Any) -> dict[str, Any]:
    remaining = conn.execute(
        "SELECT COUNT(*) FROM x_posts WHERE review_status = 'unreviewed'"
    ).fetchone()[0]
    reads_left = reads_remaining(conn)
    used = MAX_MONTHLY_POST_READS - reads_left
    counts = {"remaining": remaining, "reads_used": used, "reads_remaining": reads_left}

    posts = unreviewed_posts(conn, limit=1)
    if not posts:
        return {"empty": True, **counts}

    post = posts[0]
    thread = unreviewed_thread_posts(
        conn, post.handle, post.conversation_id, exclude_post_id=post.post_id
    )
    return {
        "empty": False,
        "post_id": post.post_id,
        "handle": post.handle,
        "posted_at": post.posted_at.isoformat(),
        "text": post.text,
        "url": post.url,
        "reply_context": post.reply_context,
        "media": [
            {"url": m.url, "media_type": m.media_type, "alt_text": m.alt_text} for m in post.media
        ],
        "thread": [
            {
                "post_id": item.post_id,
                "text": item.text,
                "posted_at": item.posted_at.isoformat(),
                "media": [
                    {"url": m.url, "media_type": m.media_type, "alt_text": m.alt_text}
                    for m in item.media
                ],
            }
            for item in thread
        ],
        **counts,
    }


def _render_reply_context(payload: dict[str, Any]) -> str:
    reply_context = payload.get("reply_context", "")
    if not reply_context:
        return ""
    return (
        '<blockquote id="reply-context">'
        f"<p><em>in reply to</em></p><p>{escape(str(reply_context))}</p>"
        "</blockquote>"
    )


def _render_media(media: list[dict[str, Any]]) -> str:
    if not media:
        return ""
    items = []
    for m in media:
        url = escape(str(m["url"]))
        media_type = str(m["media_type"])
        alt_text = escape(str(m.get("alt_text", "")))
        badge = (
            f'<span class="media-badge">{escape(media_type)}</span>'
            if media_type in ("video", "animated_gif")
            else ""
        )
        items.append(
            '<span class="media-item">'
            f'<img src="{url}" alt="{alt_text}" loading="lazy">'
            f"{badge}"
            "</span>"
        )
    return f'<div class="media">{"".join(items)}</div>'


def _render_thread(payload: dict[str, Any]) -> str:
    thread = payload.get("thread", [])
    if not thread:
        return ""
    items = "".join(
        f'<div class="thread-post" data-post-id="{escape(str(item["post_id"]))}">'
        f"<p>{escape(str(item['text']))}</p>"
        f"{_render_media(item.get('media', []))}"
        "</div>"
        for item in thread
    )
    return f'<div id="thread">{items}</div>'


def _render_post_block(payload: dict[str, Any]) -> str:
    if payload["empty"]:
        return '<p id="post-empty">No more posts to review. Queue is empty.</p>'
    post_id = escape(str(payload["post_id"]))
    handle = escape(str(payload["handle"]))
    posted_at = escape(str(payload["posted_at"]))
    text = escape(str(payload["text"]))
    url = escape(str(payload["url"]))
    reply_context = _render_reply_context(payload)
    media = _render_media(payload.get("media", []))
    thread = _render_thread(payload)
    return f"""
      <div id="post" data-post-id="{post_id}">
        {reply_context}
        <p><strong>@{handle}</strong> &mdash; {posted_at}</p>
        <p id="post-text">{text}</p>
        {media}
        {thread}
        <p><a href="{url}" target="_blank" rel="noopener">{url}</a></p>
      </div>
    """


def _render_stats(payload: dict[str, Any]) -> str:
    return (
        f'<p id="stats">remaining: {payload["remaining"]} | '
        f"reads used: {payload['reads_used']} | "
        f"reads remaining: {payload['reads_remaining']}</p>"
    )


def _radio_group(name: str, values: list[str]) -> str:
    inputs = "".join(
        f'<label><input type="radio" name="{name}" value="{escape(v)}"> {escape(v)}</label>'
        for v in values
    )
    return f'<div class="radio-group" id="group-{name}">{inputs}</div>'


def _theme_buttons() -> str:
    buttons = "".join(
        f'<label><input type="radio" name="primary_theme_id" '
        f'value="{escape(t)}"> {escape(t)}</label>'
        for t in THEMES
    )
    return f'<div class="radio-group" id="group-theme">{buttons}</div>'


def _metric_cells(prefix: str, metrics: dict[str, Any] | None) -> str:
    agreement = f"{metrics['agreement_pct']:.1f}%" if metrics else "n/a"
    precision = f"{metrics['precision']:.3f}" if metrics else "n/a"
    recall = f"{metrics['recall']:.3f}" if metrics else "n/a"
    return (
        f'<td id="{prefix}-agreement">{agreement}</td>'
        f'<td id="{prefix}-precision">{precision}</td>'
        f'<td id="{prefix}-recall">{recall}</td>'
    )


def _render_comparison(progress: dict[str, Any]) -> str:
    rows = (
        f"<tr><td>original</td>{_metric_cells('original', progress['original_metrics'])}</tr>"
        f"<tr><td>live</td>{_metric_cells('live', progress['live_metrics'])}</tr>"
        f"<tr><td>live (excl. borderline)</td>"
        f"{_metric_cells('live-excl', progress['live_metrics_excluding_borderline'])}</tr>"
    )
    return (
        '<table id="comparison-table"><thead><tr><th></th><th>agreement</th>'
        "<th>precision</th><th>recall</th></tr></thead><tbody>"
        f"{rows}</tbody></table>"
        f'<p id="progress">adjudicated {progress["adjudicated_count"]}/'
        f"{progress['total_disagreements']}</p>"
    )


def _render_disagreement_block(payload: dict[str, Any]) -> str:
    item = payload.get("next")
    if payload["empty"] or item is None:
        return '<p id="disagreement-empty">All disagreements adjudicated.</p>'
    post_id = escape(str(item["post_id"]))
    handle = escape(str(item["handle"]))
    posted_at = escape(str(item["posted_at"]))
    text = escape(str(item["text"]))
    url = escape(str(item["url"]))
    reply_context = _render_reply_context(item)
    media = _render_media(item.get("media", []))
    human_label = escape(str(item["human_label"]))
    prediction = escape(str(item["prediction"]))
    reason = escape(str(item.get("reason", "")))
    captured_note = (
        '<p id="captured-flag">captured post: overturn will not auto-flip; '
        "flagged for manual review.</p>"
        if item.get("captured")
        else ""
    )
    return f"""
      <div id="disagreement" data-post-id="{post_id}">
        {reply_context}
        <p><strong>@{handle}</strong> &mdash; {posted_at}</p>
        <p id="disagreement-text">{text}</p>
        {media}
        <p><a href="{url}" target="_blank" rel="noopener">{url}</a></p>
        {captured_note}
        <div class="label-compare">
          <div><strong>YOUR LABEL</strong>:
            <span id="disagreement-human-label">{human_label}</span></div>
          <div><strong>MODEL</strong>:
            <span id="disagreement-prediction">{prediction}</span>
            &mdash; <span id="disagreement-reason">{reason}</span></div>
        </div>
      </div>
    """


_PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>X labeling inbox</title>
<style>
body {{ font-family: sans-serif; max-width: 720px; margin: 2rem auto; }}
.radio-group label {{
  display: inline-block; margin: 0.15rem; padding: 0.2rem 0.4rem; border: 1px solid #ccc;
}}
#capture-form {{ display: none; margin-top: 1rem; }}
#reply-context {{
  border-left: 3px solid #999; margin: 0.5rem 0; padding: 0.25rem 0.75rem;
  color: #555; font-style: italic;
}}
#thread {{ border-left: 3px solid #ccc; margin: 0.5rem 0; padding-left: 0.75rem; }}
#error-banner {{
  display: none; background: #fdd; border: 1px solid #c00; color: #900;
  padding: 0.5rem 0.75rem; margin: 0.5rem 0; border-radius: 0.2rem;
}}
.media {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.5rem 0; }}
.media-item {{ position: relative; display: inline-block; }}
.media-item img {{ max-width: 100%; max-height: 320px; display: block; }}
.media-badge {{
  position: absolute; bottom: 0.25rem; left: 0.25rem; background: rgba(0, 0, 0, 0.7);
  color: #fff; font-size: 0.75rem; padding: 0.1rem 0.4rem; border-radius: 0.2rem;
}}
</style>
</head>
<body>
<h1>X labeling inbox</h1>
{stats}
<div id="error-banner"></div>
{post_block}
<div id="controls">
  <button id="skip-btn">Skip (s)</button>
  <button id="flag-btn">Significant (f)</button>
  <button id="capture-btn">Capture (c)</button>
</div>
<div id="capture-form">
  <div>
    <label>Theme</label>
    {theme_buttons}
  </div>
  <div><label>Claim <input type="text" id="claim"></label></div>
  <div><label>Tickers (comma separated) <input type="text" id="tickers"></label></div>
  <div><label>Claim type</label>{claim_type_group}</div>
  <div><label>Stance</label>{stance_group}</div>
  <div><label>Horizon</label>{horizon_group}</div>
  <div><label>Scrutiny verdict</label>{verdict_group}</div>
  <div><label>Why it matters <input type="text" id="why_it_matters"></label></div>
  <button id="submit-btn">Submit</button>
</div>
<script>
var currentThreadPostIds = [];

function renderMedia(media) {{
  if (!media || !media.length) return '';
  var items = media.map(function(m) {{
    var badge = (m.media_type === 'video' || m.media_type === 'animated_gif')
      ? '<span class="media-badge">' + m.media_type + '</span>'
      : '';
    return '<span class="media-item"><img src="' + m.url + '" alt="' + m.alt_text +
      '" loading="lazy">' + badge + '</span>';
  }}).join('');
  return '<div class="media">' + items + '</div>';
}}

function showError(message) {{
  var el = document.getElementById('error-banner');
  el.textContent = message;
  el.style.display = 'block';
}}

function clearError() {{
  var el = document.getElementById('error-banner');
  el.style.display = 'none';
  el.textContent = '';
}}

// Every response is read as JSON regardless of status so FastAPI's 422/404
// detail can be shown to the user; only an ok response is passed on to
// render, so a rejected request never gets treated as a completed capture.
function handleResponse(r) {{
  return r.json().then(function(data) {{
    if (!r.ok) {{
      var detail = data && data.detail;
      var message = Array.isArray(detail)
        ? detail.map(function(d) {{ return d.msg || JSON.stringify(d); }}).join('; ')
        : (detail || ('request failed with status ' + r.status));
      throw new Error(message);
    }}
    return data;
  }});
}}

function renderPost(payload) {{
  clearError();
  var postDiv = document.getElementById('post') || document.getElementById('post-empty');
  var html;
  if (payload.empty) {{
    currentThreadPostIds = [];
    html = '<p id="post-empty">No more posts to review. Queue is empty.</p>';
  }} else {{
    currentThreadPostIds = (payload.thread || []).map(function(t) {{ return t.post_id; }});
    var replyHtml = '';
    if (payload.reply_context) {{
      replyHtml = '<blockquote id="reply-context"><p><em>in reply to</em></p>' +
        '<p class="reply-context-text"></p></blockquote>';
    }}
    var threadHtml = '';
    if (payload.thread && payload.thread.length) {{
      threadHtml = '<div id="thread">' + payload.thread.map(function(t) {{
        return '<div class="thread-post" data-post-id="' + t.post_id +
          '"><p class="thread-post-text"></p>' + renderMedia(t.media) + '</div>';
      }}).join('') + '</div>';
    }}
    html = '<div id="post" data-post-id="' + payload.post_id + '">' +
      replyHtml +
      '<p><strong>@' + payload.handle + '</strong> &mdash; ' + payload.posted_at + '</p>' +
      '<p id="post-text"></p>' +
      renderMedia(payload.media) +
      threadHtml +
      '<p><a href="' + payload.url + '" target="_blank" rel="noopener"></a></p></div>';
  }}
  postDiv.outerHTML = html;
  if (!payload.empty) {{
    document.getElementById('post-text').textContent = payload.text;
    if (payload.reply_context) {{
      document.querySelector('.reply-context-text').textContent = payload.reply_context;
    }}
    if (payload.thread && payload.thread.length) {{
      var threadTexts = document.querySelectorAll('.thread-post-text');
      payload.thread.forEach(function(t, i) {{ threadTexts[i].textContent = t.text; }});
    }}
    var link = document.querySelector('#post a');
    link.href = payload.url;
    link.textContent = payload.url;
  }}
  document.getElementById('stats').textContent =
    'remaining: ' + payload.remaining + ' | reads used: ' + payload.reads_used +
    ' | reads remaining: ' + payload.reads_remaining;
  document.getElementById('capture-form').style.display = 'none';
}}

function currentPostId() {{
  var el = document.getElementById('post');
  return el ? el.getAttribute('data-post-id') : null;
}}

function skip() {{
  var postId = currentPostId();
  if (!postId) return;
  fetch('/api/skip', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{post_id: postId, thread_post_ids: currentThreadPostIds}})
  }}).then(handleResponse).then(renderPost).catch(function(err) {{ showError(err.message); }});
}}

function flagSignificant() {{
  var postId = currentPostId();
  if (!postId) return;
  fetch('/api/flag', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{post_id: postId, thread_post_ids: currentThreadPostIds}})
  }}).then(handleResponse).then(renderPost).catch(function(err) {{ showError(err.message); }});
}}

function openCapture() {{
  if (!currentPostId()) return;
  document.getElementById('capture-form').style.display = 'block';
}}

function radioValue(name) {{
  var el = document.querySelector('input[name="' + name + '"]:checked');
  return el ? el.value : null;
}}

function submitCapture() {{
  var postId = currentPostId();
  if (!postId) return;
  var body = {{
    post_id: postId,
    thread_post_ids: currentThreadPostIds,
    primary_theme_id: radioValue('primary_theme_id'),
    tickers: document.getElementById('tickers').value.split(',')
      .map(function(t) {{ return t.trim(); }}).filter(Boolean),
    claim: document.getElementById('claim').value,
    claim_type: radioValue('claim_type'),
    stance: radioValue('stance'),
    horizon: radioValue('horizon'),
    scrutiny_verdict: radioValue('scrutiny_verdict'),
    why_it_matters: document.getElementById('why_it_matters').value
  }};
  // Every field below is required by the server's CaptureRequest model; a
  // missed radio button used to reach the server as null, get rejected,
  // and silently strand the post as unreviewed. Catch it here instead.
  var missing = [];
  if (!body.primary_theme_id) missing.push('theme');
  if (!body.claim_type) missing.push('claim type');
  if (!body.stance) missing.push('stance');
  if (!body.horizon) missing.push('horizon');
  if (!body.scrutiny_verdict) missing.push('scrutiny verdict');
  if (!body.claim.trim()) missing.push('claim');
  if (missing.length) {{
    showError('Select before submitting: ' + missing.join(', '));
    return;
  }}
  fetch('/api/capture', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body)
  }}).then(handleResponse).then(renderPost).catch(function(err) {{ showError(err.message); }});
}}

document.getElementById('skip-btn').addEventListener('click', skip);
document.getElementById('flag-btn').addEventListener('click', flagSignificant);
document.getElementById('capture-btn').addEventListener('click', openCapture);
document.getElementById('submit-btn').addEventListener('click', submitCapture);
document.addEventListener('keydown', function(e) {{
  var tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if (e.key === 's') skip();
  if (e.key === 'f') flagSignificant();
  if (e.key === 'c') openCapture();
}});
</script>
</body>
</html>
"""


def _render_page(payload: dict[str, Any]) -> str:
    return _PAGE_TEMPLATE.format(
        stats=_render_stats(payload),
        post_block=_render_post_block(payload),
        theme_buttons=_theme_buttons(),
        claim_type_group=_radio_group("claim_type", [e.value for e in ClaimType]),
        stance_group=_radio_group("stance", [e.value for e in Stance]),
        horizon_group=_radio_group("horizon", [e.value for e in Horizon]),
        verdict_group=_radio_group("scrutiny_verdict", [e.value for e in ScrutinyVerdict]),
    )


_ADJUDICATE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Adjudication: {predictor}</title>
<style>
body {{ font-family: sans-serif; max-width: 720px; margin: 2rem auto; }}
table#comparison-table {{ border-collapse: collapse; margin-bottom: 0.5rem; }}
table#comparison-table td, table#comparison-table th {{
  padding: 0.2rem 0.6rem; border: 1px solid #ccc; text-align: right;
}}
table#comparison-table td:first-child, table#comparison-table th:first-child {{
  text-align: left;
}}
#reply-context {{
  border-left: 3px solid #999; margin: 0.5rem 0; padding: 0.25rem 0.75rem;
  color: #555; font-style: italic;
}}
#error-banner {{
  display: none; background: #fdd; border: 1px solid #c00; color: #900;
  padding: 0.5rem 0.75rem; margin: 0.5rem 0; border-radius: 0.2rem;
}}
#captured-flag {{ color: #900; font-style: italic; }}
.label-compare {{ display: flex; gap: 1.5rem; margin: 0.75rem 0; }}
.media {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.5rem 0; }}
.media-item {{ position: relative; display: inline-block; }}
.media-item img {{ max-width: 100%; max-height: 320px; display: block; }}
.media-badge {{
  position: absolute; bottom: 0.25rem; left: 0.25rem; background: rgba(0, 0, 0, 0.7);
  color: #fff; font-size: 0.75rem; padding: 0.1rem 0.4rem; border-radius: 0.2rem;
}}
</style>
</head>
<body>
<h1>Adjudication: {predictor}</h1>
<div id="comparison">{comparison}</div>
<div id="error-banner"></div>
{disagreement_block}
<div id="controls">
  <button id="uphold-btn">Uphold mine (1)</button>
  <button id="overturn-btn">Model was right (2)</button>
  <button id="borderline-btn">Borderline (3)</button>
</div>
<div><label>Note <input type="text" id="note"></label></div>
<script>
var predictor = {predictor_json};

function renderMedia(media) {{
  if (!media || !media.length) return '';
  var items = media.map(function(m) {{
    var badge = (m.media_type === 'video' || m.media_type === 'animated_gif')
      ? '<span class="media-badge">' + m.media_type + '</span>'
      : '';
    return '<span class="media-item"><img src="' + m.url + '" alt="' + m.alt_text +
      '" loading="lazy">' + badge + '</span>';
  }}).join('');
  return '<div class="media">' + items + '</div>';
}}

function showError(message) {{
  var el = document.getElementById('error-banner');
  el.textContent = message;
  el.style.display = 'block';
}}

function clearError() {{
  var el = document.getElementById('error-banner');
  el.style.display = 'none';
  el.textContent = '';
}}

// Every response is read as JSON regardless of status so FastAPI's 422/404
// detail can be shown to the user; only an ok response is passed on to
// render, so a rejected request never gets treated as a completed verdict.
function handleResponse(r) {{
  return r.json().then(function(data) {{
    if (!r.ok) {{
      var detail = data && data.detail;
      var message = Array.isArray(detail)
        ? detail.map(function(d) {{ return d.msg || JSON.stringify(d); }}).join('; ')
        : (detail || ('request failed with status ' + r.status));
      throw new Error(message);
    }}
    return data;
  }});
}}

function currentPostId() {{
  var el = document.getElementById('disagreement');
  return el ? el.getAttribute('data-post-id') : null;
}}

function metricsRow(prefix, m) {{
  var agreement = m ? m.agreement_pct.toFixed(1) + '%' : 'n/a';
  var precision = m ? m.precision.toFixed(3) : 'n/a';
  var recall = m ? m.recall.toFixed(3) : 'n/a';
  document.getElementById(prefix + '-agreement').textContent = agreement;
  document.getElementById(prefix + '-precision').textContent = precision;
  document.getElementById(prefix + '-recall').textContent = recall;
}}

function renderComparison(payload) {{
  metricsRow('original', payload.original_metrics);
  metricsRow('live', payload.live_metrics);
  metricsRow('live-excl', payload.live_metrics_excluding_borderline);
  document.getElementById('progress').textContent =
    'adjudicated ' + payload.adjudicated_count + '/' + payload.total_disagreements;
}}

function renderDisagreement(payload) {{
  var container = document.getElementById('disagreement') ||
    document.getElementById('disagreement-empty');
  var item = payload.next;
  var html;
  if (payload.empty || !item) {{
    html = '<p id="disagreement-empty">All disagreements adjudicated.</p>';
  }} else {{
    var replyHtml = '';
    if (item.reply_context) {{
      replyHtml = '<blockquote id="reply-context"><p><em>in reply to</em></p>' +
        '<p class="reply-context-text"></p></blockquote>';
    }}
    var capturedHtml = item.captured
      ? '<p id="captured-flag">captured post: overturn will not auto-flip; ' +
        'flagged for manual review.</p>'
      : '';
    html = '<div id="disagreement" data-post-id="' + item.post_id + '">' +
      replyHtml +
      '<p><strong>@' + item.handle + '</strong> &mdash; ' + item.posted_at + '</p>' +
      '<p id="disagreement-text"></p>' +
      renderMedia(item.media) +
      '<p><a href="' + item.url + '" target="_blank" rel="noopener"></a></p>' +
      capturedHtml +
      '<div class="label-compare">' +
      '<div><strong>YOUR LABEL</strong>: <span id="disagreement-human-label"></span></div>' +
      '<div><strong>MODEL</strong>: <span id="disagreement-prediction"></span>' +
      ' &mdash; <span id="disagreement-reason"></span></div></div></div>';
  }}
  container.outerHTML = html;
  if (!payload.empty && item) {{
    document.getElementById('disagreement-text').textContent = item.text;
    if (item.reply_context) {{
      document.querySelector('.reply-context-text').textContent = item.reply_context;
    }}
    var link = document.querySelector('#disagreement a');
    link.href = item.url;
    link.textContent = item.url;
    document.getElementById('disagreement-human-label').textContent = item.human_label;
    document.getElementById('disagreement-prediction').textContent = item.prediction;
    document.getElementById('disagreement-reason').textContent = item.reason || '';
  }}
  var note = document.getElementById('note');
  if (note) note.value = '';
}}

function renderPayload(payload) {{
  clearError();
  renderComparison(payload);
  renderDisagreement(payload);
}}

function submitVerdict(verdict) {{
  var postId = currentPostId();
  if (!postId) return;
  var note = document.getElementById('note').value;
  fetch('/api/adjudicate', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{predictor: predictor, post_id: postId, verdict: verdict, note: note}})
  }}).then(handleResponse).then(renderPayload).catch(function(err) {{ showError(err.message); }});
}}

document.getElementById('uphold-btn').addEventListener('click', function() {{
  submitVerdict('upheld');
}});
document.getElementById('overturn-btn').addEventListener('click', function() {{
  submitVerdict('overturned');
}});
document.getElementById('borderline-btn').addEventListener('click', function() {{
  submitVerdict('borderline');
}});
document.addEventListener('keydown', function(e) {{
  var tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;
  if (e.key === '1') submitVerdict('upheld');
  if (e.key === '2') submitVerdict('overturned');
  if (e.key === '3') submitVerdict('borderline');
}});
</script>
</body>
</html>
"""


def _render_adjudicate_page(predictor: str, payload: dict[str, Any]) -> str:
    return _ADJUDICATE_TEMPLATE.format(
        predictor=escape(predictor),
        predictor_json=json.dumps(predictor),
        comparison=_render_comparison(payload),
        disagreement_block=_render_disagreement_block(payload),
    )


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI()
    app.state.db_path = str(db_path)

    # Each request opens (and closes) its own sqlite3 connection rather than
    # sharing one across requests. sqlite3 connections are thread-bound and
    # FastAPI runs sync path functions in a threadpool, so a shared connection
    # would either need check_same_thread=False (silently unsafe for
    # concurrent writers) or a lock; per-request connections sidestep both and
    # cost little since connect() only opens a local file and idempotently
    # re-applies CREATE TABLE IF NOT EXISTS.
    def get_conn() -> Any:
        return connect(app.state.db_path)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        conn = get_conn()
        try:
            payload = _next_payload(conn)
        finally:
            conn.close()
        return _render_page(payload)

    @app.get("/api/next")
    def api_next() -> dict[str, Any]:
        conn = get_conn()
        try:
            return _next_payload(conn)
        finally:
            conn.close()

    @app.post("/api/skip")
    def api_skip(body: SkipRequest) -> dict[str, Any]:
        conn = get_conn()
        try:
            mark_reviewed(conn, body.post_id, "skipped")
            for thread_post_id in body.thread_post_ids:
                mark_reviewed(conn, thread_post_id, "skipped")
            return _next_payload(conn)
        finally:
            conn.close()

    @app.post("/api/flag")
    def api_flag(body: SkipRequest) -> dict[str, Any]:
        conn = get_conn()
        try:
            mark_reviewed(conn, body.post_id, "significant")
            for thread_post_id in body.thread_post_ids:
                mark_reviewed(conn, thread_post_id, "significant")
            return _next_payload(conn)
        finally:
            conn.close()

    @app.post("/api/capture")
    def api_capture(body: CaptureRequest) -> dict[str, Any]:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT handle, posted_at, url FROM x_posts WHERE post_id = ?",
                (body.post_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"post {body.post_id} not found")
            handle, posted_at, url = row

            entry_id = f"xs_{body.post_id}"
            # Reuse the original captured_at on a re-capture of the same post
            # so identical resubmissions produce byte-identical signal JSON —
            # otherwise a fresh now() on every call would make save_signal's
            # idempotency check (exact JSON match) never succeed.
            existing = conn.execute(
                "SELECT signal_json FROM x_signals WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            captured_at = (
                CapturedSignal.model_validate_json(existing[0]).captured_at
                if existing is not None
                else datetime.now(UTC)
            )

            signal = CapturedSignal(
                entry_id=entry_id,
                post_id=body.post_id,
                captured_at=captured_at,
                post_url=url,
                handle=handle,
                posted_at=posted_at,
                primary_theme_id=body.primary_theme_id,
                tickers=body.tickers,
                claim=body.claim,
                claim_type=body.claim_type,
                stance=body.stance,
                horizon=body.horizon,
                scrutiny_verdict=body.scrutiny_verdict,
                why_it_matters=body.why_it_matters,
            )
            save_signal(conn, signal)
            # One signal is captured against the anchor; the rest of the same
            # thread is consolidated into this single review action, so those
            # posts are marked captured without separate signal rows.
            for thread_post_id in body.thread_post_ids:
                thread_row = conn.execute(
                    "SELECT review_status FROM x_posts WHERE post_id = ?",
                    (thread_post_id,),
                ).fetchone()
                if thread_row is not None and thread_row[0] == "unreviewed":
                    mark_reviewed(conn, thread_post_id, "captured")
            return _next_payload(conn)
        finally:
            conn.close()

    @app.get("/adjudicate", response_class=HTMLResponse)
    def adjudicate_page(predictor: str) -> str:
        conn = get_conn()
        try:
            payload = next_payload(conn, predictor)
        finally:
            conn.close()
        return _render_adjudicate_page(predictor, payload)

    @app.get("/api/adjudicate/next")
    def api_adjudicate_next(predictor: str) -> dict[str, Any]:
        conn = get_conn()
        try:
            return next_payload(conn, predictor)
        finally:
            conn.close()

    @app.post("/api/adjudicate")
    def api_adjudicate(body: AdjudicateRequest) -> dict[str, Any]:
        conn = get_conn()
        try:
            try:
                return adjudicate(conn, body.predictor, body.post_id, body.verdict, body.note)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            conn.close()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.labeling.server")
    parser.add_argument("--db", default="data/boustrategy.db")
    args = parser.parse_args()

    app = create_app(args.db)

    import uvicorn

    # Loopback only — the post text is the project's private archive. Host is
    # a literal, never a parameter: this must never be exposed to the network.
    uvicorn.run(app, host="127.0.0.1", port=8377)


if __name__ == "__main__":
    main()
