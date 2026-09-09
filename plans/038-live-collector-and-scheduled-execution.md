# Plan 038: Live collector and scheduled execution on the Agentic account

## Status

- **Priority**: P0
- **Effort**: M
- **Risk**: HIGH (real orders; bounded by the $20 per-order cap and the Agentic account balance)
- **Depends on**: Plan 031 runtime, the ops wrappers committed 2026-09-09
- **Planned and built**: 2026-09-09 on `main`, at the maintainer's direction to skip the paper phase

## Decision this plan implements

The maintainer funded Robinhood's dedicated Agentic account with about $100 as the low-stakes
envelope and asked for live buys from the first scheduled review, not paper fills. Live-money
activation was already a resolved human checkpoint (2026-08-27). This plan supplies the two
capabilities the execution assessment named as the remaining live blockers:

1. a **live schedule revision** bound to the `codex` profile, and
2. a **trusted account collector** plus a **scheduled executor**, so a fresh broker snapshot
   exists whenever the runtime submits and a policy-approved intent is placed the next session.

No policy, limit or approval setting changes. The deterministic gate, the fingerprint checks, the
packet builder, the lifecycle ledger and the quote-age rule are the same code the audit reviewed.

## Design

### Broker sessions (`app/broker/session.py`)

Robinhood is reachable only through its MCP server, and the OAuth grant lives in the bot's Codex
home. Rather than reverse-engineer that grant, a broker session is one bounded `codex exec` run
with the bot's home, a strict output schema, a restricted environment and a hard timeout. It
returns one Pydantic object; trusted code validates it before anything is persisted. This is the
same shape as the authoring runner, with the opposite configuration: user config loaded so the
MCP server is available.

### Collector (`app/broker/collector.py`)

- `collect_snapshot` asks a read-only session to identify the account whose SHA-256 fingerprint
  matches the profile (the grant also exposes personal accounts), read portfolio and positions,
  and return them. The module rejects any other fingerprint, attaches each position's
  `primary_theme_id` from the decision that opened it, and saves through
  `save_live_portfolio_snapshot`.
- `collect_preflight` does the same for a ticker-bound quote and tradability read.
- CLI: `snapshot`, `preflight --ticker`, and `prepare-live --slot --model-label --out`, which
  captures the snapshot and creates the PREPARED reasoning run in one process so the five-minute
  freshness window cannot lapse between the two.

### Worker hook (`app/reason/worker.py`)

`execute_attempt` accepts `snapshot_collector`. In live mode it calls it before the readiness
check and again before submission when the model authored decisions. A collector failure blocks
the attempt with `snapshot_stale`; it never submits against old facts. The runtime CLI builds the
collector for live runs (`--collector-model`, default `gpt-5.6-luna`).

### Executor (`app/broker/executor.py`)

`execute_pending` lists LIVE intents for the profile that have no broker execution record and are
younger than 48 hours, then runs one workspace-write broker session per intent. The session
follows `docs/execution/EXECUTOR.md`, whose new "Tool and record mapping" section pins the exact
Robinhood tools, the preflight JSON, the packet command, the review and single placement with
`ref_id` equal to the packet id, and the record and event commands. Afterwards `verify_report`
compares the session's report against the ledger: a reported placement without a record, or a
record without a reported placement, is a named problem, written to `executions.jsonl`, returned
with exit code 1, and surfaced as attention.

### Host tasks (`ops/`)

- `run-live-prepare.ps1` at 18:10 (15:10 half-days): deterministic market preparation, then
  `collector prepare-live`.
- `run-review-poller.ps1` now ticks `live-close` with `--live-profiles` and `--collector-model`.
- `run-live-execution.ps1` at 09:35 and 12:15 weekdays runs the executor.
- Schedule `live-close` revision 1 (18:15 due, 15:15 half-day, 30-minute grace); `paper-close`
  revision 3 disabled.

## Verification

- `tests/broker/test_session.py`: schema enforcement, environment isolation, named failures.
- `tests/broker/test_collector.py`: fingerprint rejection, theme attachment, snapshot persistence,
  preflight mapping.
- `tests/broker/test_executor.py`: pending-intent selection, session invocation, ledger
  verification, session failure reporting.
- `tests/reason/test_runtime.py`: the worker refreshes through the collector twice and submits with
  the second snapshot; a collector failure blocks before authoring.
- Full suite, ruff and mypy green.

## Operating notes and STOP conditions

- The first live review should be watched on the Operations page: the attempt row, then the next
  morning's `executions.jsonl` line.
- A `problems` entry other than an empty list in `executions.jsonl` means the ledger and the
  broker may disagree. Check Robinhood's order history for that packet id before anything else.
- Robinhood tool enumerations for side, order type, time in force and market hours were not
  exercised by tests; the first execution session's log is the check.
- If the Agentic account ever shows positions the ledger does not know about, stop the execute
  task and reconcile by hand.
