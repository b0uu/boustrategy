# Plan 025: Reasoning worker harness + prompt drafts — build everything, run nothing

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/025-reasoning-worker`, do NOT push, don't
> touch plans/README.md. Never edit maintainer-owned strategy docs.
> **This plan ends AT human checkpoint 5 — you build the worker and
> draft its prompts; you never launch a reasoning session or author a
> real decision record. There is no exception.**

## Status

- Priority P1. Effort M-L. Depends on 018/019 (digest + ACTIONABLE),
  021 (calendar), 022 (triggers), 023 (regime snapshots), 024 (paper
  broker + PortfolioContext) — all hard. Planned at local main
  `460977d`, 2026-07-18.

## Why this matters

This is the last buildable plan before the human-in-the-loop wall.
Checkpoint 5 gates the first decision-generating RUN, not the build:
"reasoning prompts can be drafted from the docs, but the maintainer
approves before any decision-generating run." So this plan delivers the
complete worker — intake bundle, prompt drafts, submission CLI, session
runbook — in a state where the maintainer's sign-off is the only thing
between it and paper operation. Execution model per the 2026-07-15
decision: a subscription agent session driving a CLI (MCP explicitly
deferred); the enforced boundary is that a session can only create
decisions through `submit`, which runs the full schema + policy + intent
pipeline — no direct path from LLM output to an order intent.

## Current state (local main `460977d` + plans 018-024 merged)

- `app/state/pipeline.py`: `process_decision(conn, record_data,
  portfolio)` — validate → persist → policy → order intent, idempotent
  status trail.
- `app/paper/context.py`: `portfolio_context(conn, on_date,
  exclude_ticker)`.
- `app/triggers/run.py`: `list`/`mark`; `app/regime/`:
  `regime_snapshots`; digests at `data/digests/<date>.md` with
  ACTIONABLE marker; `x_article_queue`; `docs/watchlist.md`.
- Maintainer-owned inputs the prompts must READ AT RUNTIME (never copy
  into prompts — they are tunable): `docs/mandate.md`,
  `docs/risk_policy.md`, `docs/risk_posture.md`, `docs/source_policy.md`.

## Scope

IN: `app/reason/` (create: `intake.py`, `run.py`), `docs/prompts/`
(create: two DRAFT prompt docs), `docs/reasoning/RUNBOOK.md` (create),
the two one-line wire-ins deferred from 024 (position tickers unioned
into events `refresh` and triggers `evaluate`), tests.
OUT: launching any session; scheduling; eval harness (post-worker, its
own plan); any edit to maintainer-owned docs; broker adapter anything.

## Design

### `python -m app.reason.run intake [--date] --out DIR`

Assembles the decision-context bundle, one self-contained directory a
session reads cold:

- `bundle.md` — human/agent-readable index: latest published regime +
  score components (with an explicit `RULES NOT YET SIGNED OFF` banner
  until the maintainer clears plan 023's REVIEW-REQUIRED — the banner
  text is part of this plan), pending triggers (IDs + details), the
  last 3 daily digests' paths + their headline items inline, pending
  article-queue items, paper positions/equity/cash, today's intake
  quota state from `portfolio_context`, upcoming calendar events
  (7 days), and pointers (paths, not copies) to the four
  maintainer-owned docs + the two prompts.
- `portfolio.json`, `triggers.json` — machine-readable versions.
- Prints the bundle path. Read-only against the db; never mutates.

### `python -m app.reason.run submit --in FILE [--date]`

- FILE = one JSON decision record authored by the session.
- Builds `portfolio_context(conn, date, exclude_ticker=record ticker)`,
  calls `process_decision`, prints the full outcome (final status,
  policy reasons, order intent id).
- `--consume-triggers ID,ID` optional: on POLICY_APPROVED or
  POLICY_REJECTED (i.e., the record was genuinely considered), marks
  those triggers consumed via plan 022's transition API. A schema-failed
  submit consumes nothing.
- No other write path. This is the no-direct-LLM-to-order containment:
  sessions hold no SQL, only `intake` and `submit`.

### `docs/prompts/thesis_chain.md` and `docs/prompts/daily_management.md`

Both begin with this banner, verbatim:

> **DRAFT — PENDING HUMAN CHECKPOINT 5 SIGN-OFF. No decision-generating
> session may load this prompt until the maintainer approves it and
> records the approval in plans/README.md.**

Draft them FROM the maintainer-owned docs. Required elements (executor
drafts the prose; these are the must-cover checkpoints):

- Epistemic stance imported by reference from `docs/mandate.md`
  (decisive, calibrated, variant perception, no hedging-mush) and
  sizing/appetite imported by reference from `docs/risk_posture.md`
  (conviction tiers with the undersizing-is-a-violation rule) — the
  prompt instructs READING those files, quoting none of their numbers.
- Thesis chain: claim → substantiation (source claims with the
  `confirmed_outside_x` discipline from `docs/source_policy.md`) →
  counter-thesis seriously argued → invalidation criteria (mandatory,
  concrete, checkable) → conviction tier placement → decision record
  JSON, exact `InvestmentDecisionRecord` schema, ending in `submit`.
- Daily management: review positions against invalidation criteria and
  new digest/trigger evidence; the invalidation-hit → same-day-review
  and −40% rules from `docs/risk_policy.md`; explicit permission to
  conclude "no action" (most days should).
- Extraordinary-opportunity bar: rare by doctrine; frequency is
  tracked; a quota override (plan 020) requires the written
  justification to argue why THIS week's catalyst can't wait for
  tomorrow's quota.
- Both prompts forbid: fabricating source claims, citing the digest as
  outside-X confirmation (it IS X), and any instruction to skip
  `submit`.

### `docs/reasoning/RUNBOOK.md`

Session procedure: `paper settle` (fills yesterday's intents) →
`triggers evaluate` → `regime score` → `intake` → read bundle + prompts
→ author zero or more decision records → `submit` each → append a
dated session log under `data/reasoning_sessions/<date>.md` (what was
considered, what was declined and why — the "no action" record is eval
gold). Prohibitions printed verbatim: never edit digests/labels/roster/
maintainer docs; never write to the db except via `submit`; never
continue into digester work (separate seam, separate session).

## Steps

1. `intake` + bundle rendering (tests: synthetic db → assert every
   section present, regime banner logic, read-only guarantee).
2. `submit` + trigger consumption rules (tests: approved/rejected/
   schema-failed × consumption matrix; exclude_ticker plumbed; outcome
   printing).
3. The two 024-deferred wire-ins (position tickers → events refresh,
   triggers evaluate), with tests.
4. Prompt drafts + runbook per the required-elements lists. Include the
   DRAFT banners. Cross-check every CLI reference against the
   implemented flags.
5. Gates: pytest -q, ruff check, ruff format --check, mypy app tests →
   all exit 0; `git status --porcelain` clean after commit.

## STOP conditions

- Any dependency plan unmerged, or its surface drifted.
- You find yourself running a reasoning session, authoring a decision
  record about a real ticker outside test fixtures, or scheduling
  anything.
- You find yourself copying numbers from maintainer-owned docs into
  prompts (they must be read at runtime).
- Current-state signatures don't match.

## Maintenance notes

- **The wall (checkpoint 5)**: after this merges, the maintainer (1)
  reviews/edits the two prompts and the regime rule table, (2) records
  sign-off in plans/README.md, (3) runs the first paper session
  supervised, (4) schedules recurring sessions. None of that is
  executor work.
- The eval harness (forward capsules, extraordinary-frequency metric,
  counter-thesis kill rate) becomes plan-worthy the day the first paper
  sessions produce records — plan it then, against real session logs.
- Model choice for the reasoning session is a maintainer call recorded
  in NOTES (quality over frequency; e.g. Fable-class); the runbook
  deliberately doesn't hardcode a model.
