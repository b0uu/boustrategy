# Completed plan archive

Completed plans 001-031 and the audit history that produced them. The live index is ../README.md. Maintainer decisions remain in the live index because they still govern the code.

## Execution order & status

Recommended order: 001 → 002 → 003 → 004 → 005 → 006 → 007, with 008
runnable at any point in parallel (it is research-only and touches no code).
**Wave 018-027 is complete.** Paper reasoning has since run, checkpoint 5
is cleared, and the broker-neutral live ledger exists. Plans 028-030 are
the current sequential path: simplify the live foundation, isolate the two
reasoning/account profiles, then expose the workflow in the private dashboard.
The public showcase dashboard is explicitly deferred.

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001  | Tighten InvestmentDecisionRecord schema + escalation/primary-theme fields | P1 | S | — | DONE (verified 2026-07-10) |
| 002  | Correct policy gate scoping (escalation gate for RED/derisking; weight and X rule fixes) | P1 | S | 001 (hard) | DONE (verified 2026-07-10) |
| 003  | Portfolio-aware policy rules (quotas, holdings, theme cap); remove dead sizing field | P2 | M | 001, 002 (hard) | DONE (verified 2026-07-10) |
| 004  | DX baseline: ruff, mypy, root AGENTS.md | P2 | S | — | DONE (verified 2026-07-10) |
| 005  | Order Intent schema + creation from approved decisions | P2 | M | 001-003 | DONE (verified 2026-07-10) |
| 006  | Persist decision records and order intents (SQLite, idempotent, append-only) | P2 | M | 005 | DONE (verified 2026-07-10) |
| 007  | Daily OHLCV price cache (yfinance, injected-fetcher seam) | P3 | M | 006, 004 (for editable install) | DONE (verified 2026-07-10; live check: 20 QQQ bars) |
| 008  | Research spike: X access, Unusual Whales MCP, low-cost data providers | P2 | M | — (needs web access) | DONE (verified 2026-07-10; decisions resolved 2026-07-12) |
| 009  | Backend state machine: decision pipeline, status log, crash-safe resume | P1 | M | 005, 006 | DONE (verified 2026-07-12) |
| 010  | X ingestion v0.1: account graph, core-tier fetch, human review trial | P1 | L | 006 (soft-order after 009) | DONE (verified 2026-07-12; one REVISE round fixed a since_id lexicographic-comparison bug inherited from the plan text; live trial pending X_BEARER_TOKEN) |
| 011  | Local labeling interface: button-click review inbox for the trial | P1 | M | 010 | DONE (verified 2026-07-12; one approved deviation: capture endpoint reuses stored captured_at on identical re-submits so save_signal's idempotency contract is reachable via the API) |
| 012  | Thread context: parent-post capture, conversation grouping, consolidated review | P1 | M | 010, 011 | DONE (verified 2026-07-13; migration proven against a copy of the live trial db — 1,398 rows intact) |
| 013  | Media capture: fetch image/video metadata, render inline in review UI | P1 | M | 012 | DONE (verified 2026-07-13; migration proven against a live-db copy; media excluded from billed reads) |
| 014  | Backfill rehydration: enrich pre-012/013 unreviewed posts by ID lookup | P1 | S-M | 012, 013 | DONE (verified 2026-07-14; ran same day: 1,348 enriched, 0 missing) |
| 015  | Gate-agreement harness: blind export / ingest / score for subscription-agent judging | P1 | S-M | trial labels | DONE (verified 2026-07-15; Luna judged all 1,761: 72.5% agreement, 485 disagreements — report at data/gate_experiment/report-luna.md) |
| 016  | Adjudication UI: resolve disagreements, correct labels auditably, re-score, compare rounds | P1 | M | 011, 015 | DONE (verified 2026-07-16; smoke-tested against a live-db copy; captured posts never auto-flip; label corrections audited with label_before) |
| 017  | Micro-fix: retweets store full original text (was ~140-char truncated echo; 222 historical RTs affected) | P1 | S | — | DONE (verified 2026-07-16; zero-cost — includes already fetched; historical RT repair deferred, ~500 reads, pending X balance headroom) |
| 018  | X pipeline backbone: run ledger, routing store, article queue, digest renderer, market calendar | P1 | M | 010-014 | DONE (verified 2026-07-18; merged `ec3d845`) |
| 019  | Digester session runbooks + gate rubric v2 (docs only) | P1 | S | 018 (hard) | DONE (verified 2026-07-18; merged `85e287c`) |
| 020  | Extraordinary-opportunity override for BUY/ADD daily quota (+5/day brake) | P2 | S | maintainer amends risk_policy.md first | DONE (verified 2026-07-18; merged `bd1cb00`) |
| 021  | Events calendar ingestion: watchlist earnings + FOMC | P2 | S-M | 004, 007; soft 018 | DONE (verified 2026-07-18; merged `27d996b`/`af690c8`; live FOMC + NVDA earnings check) |
| 022  | Trigger system v0: price/volume, calendar proximity, digest headlines | P2 | M | 007, 018, 021 (hard) | DONE (verified 2026-07-18; merged `fb914bc`) |
| 023  | Regime scorer v0: deterministic GREEN/YELLOW/RED + backtest report | P1 | M | 007 (hard) | DONE (verified 2026-07-18; merged `a52c7da`; backtest report `docs/research/regime_backtest_v0.md`, sign-off pending) |
| 024  | Paper broker: simulated fills, positions, real PortfolioContext | P1 | M | 005-007, 009 | DONE (verified 2026-07-18; merged `9dae08a`) |
| 025  | Reasoning worker harness + prompt drafts (builds all, runs nothing — ends AT checkpoint 5) | P1 | M-L | 018-024 (hard) | DONE (verified 2026-07-18; merged `5e88d2f`; prompts carry DRAFT banner, checkpoint 5 not yet cleared) |
| 026  | Dashboard v0: localhost read-only panel over all stores | P2 | M | 006; renders others if present | DONE (verified 2026-07-18; merged `857e33a`) |
| 027  | Newsletter ingestion v0: drop folder, archive, annotation store | P3 | S-M | 006; soft 019 | DONE (verified 2026-07-18; merged `da97255`) |
| 028  | Reconcile doctrine and simplify the live execution foundation | P1 | M | - | DONE (verified 2026-08-27; `43650f4`) |
| 029  | Isolate controlled Codex/Claude reasoning and live portfolio state | P1 | L | 028 | DONE (verified 2026-08-27; `8ce2ce3`) |
| 030  | Add the dual-agent live workflow to the private operator dashboard | P1 | M | 029 | DONE (verified 2026-08-27; `7de7f19`) |

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) |
REJECTED (with one-line rationale)

## Dependency notes

- 028 must land first because it removes the incorrect hard equity ceiling
  and stale documentation before new live state builds on those contracts.
- 029 depends on 028 and creates the profile-specific reasoning and portfolio
  state required to prevent Codex and Claude from sharing paper quotas or
  holdings.
- 030 depends on 029 because the operator interface must render real run and
  account state rather than inventing a second source of truth.
- A public showcase dashboard is not part of plans 028-030. It remains a
  separate future product surface with a strict public-data allowlist.

- 002 requires 001 (hard): the escalation gate reads the
  `extraordinary_opportunity` / `extraordinary_justification` fields plan
  001 adds to the schema.
- 003 requires 001 (hard: reads `primary_theme_id`) and 002 (hard: both
  rewrite `evaluate_decision_policy`).
- 005 assumes the post-003 `PolicyResult` shape (no
  `adjusted_final_target_weight`).
- 006 requires 005 (persists `OrderIntent`); 007 requires 006 (extends the
  storage module's schema).
- 004 is independent and may run first; if it lands, later plans must also
  pass the ruff/mypy gates it introduces (each plan says so).
- 008 is independent, research-only, and requires an executor with web
  access.

## Direction items not yet planned

- ~~X ingestion build~~ — PLANNED 2026-07-18 as plans 018 (deterministic
  backbone) + 019 (rubric v2 + session runbooks). Still outstanding from
  the original item: the scrutiny-event record schema for the account
  ledger (`docs/source_policy.md`), and the dashboard admin-only surface
  for dynamic graph editing (human-only curation, better tooling — the
  public side shows it read-only if at all). Prerequisites before first
  production cycle (maintainer): trim roster toward ~20, recalibrate
  `MAX_MONTHLY_POST_READS`, schedule the four recurring sessions (ops
  note in plan 019).
- Backend state machine (order intent status transitions, crash recovery) —
  next natural plan after 006; write it once 005/006 land and the shape is
  proven.
- ~~Reasoning prompts~~ — PLANNED 2026-07-18 as plan 025 (drafts + worker
  harness; the run itself stays behind checkpoint 5).
- ~~Public dashboard~~ — the private localhost v0 is PLANNED 2026-07-18 as
  plan 026; the PUBLIC dashboard (hosting, auth, claim-summary-only X
  rendering, "source deleted" markers) remains unplanned and is the part
  that carries the compensating-risk-control duty in full.
- LLM evals on past trades (spec §15) — includes the extraordinary-bar
  frequency metric and the counter-thesis kill-rate metric
  (`docs/source_policy.md`). Maintainer decision 2026-07-12: **forward
  capsules** are the primary replay mechanism — the append-only stores make
  every week of operation a sealed time capsule, guaranteed fresher than
  any reasoning model's training cutoff (backward replay on old data mostly
  measures the model's memory of outcomes; use old capsules for
  process-quality evals only). The trial week is capsule #1. Eval harness
  becomes plan-worthy only after the reasoning prompts/worker exist
  (human checkpoint 5).
- X article reader (2026-07-16): 59 article-pattern posts in trial data at
  76% positive — the feed's highest value-density class, invisible to the
  API (read endpoints don't exist; verified twice). Path: pilot Grok
  (sanctioned native X access, fits subscription-agent stance) as a daily
  article summarizer; human-routed via digest flags meanwhile. Gate design
  rule regardless: link-only posts from roster accounts are NEVER
  auto-skipped — always routed to the article queue. *Update 2026-07-18*:
  the queue + code-enforced always-flag routing land in plan 018; the
  reader (Grok pilot, writes `x_article_queue` status transitions)
  remains unplanned.
- ~~Curated newsletter ingestion~~ — v0 (drop folder, archive, annotation
  store) PLANNED 2026-07-18 as plan 027. The per-source email-parsing
  decision stays open with the maintainer; a future feeder reuses 027's
  ingest path.
- ~~Events calendar ingestion~~ — PLANNED 2026-07-18 as plan 021
  (watchlist earnings + FOMC; other macro prints deferred).
- ~~Trigger system build~~ — v0 PLANNED 2026-07-18 as plan 022 (price/
  volume thresholds, calendar proximity, digest headlines; nothing else).
- Regime scorer v1 inputs (credit spreads, breadth, rates) — only after
  v0 (plan 023) earns sign-off and shows its gaps.
- Reliable market-data provider (maintainer direction 2026-07-18, paid
  OK): Massive/Polygon primary for daily bars with yfinance demoted to
  fallback, Alpha Vantage earnings calendar replacing yfinance earnings
  estimates. Plan it after the v0 stack runs and shows where yfinance
  actually hurts; the injected-fetcher seams (007/021) are the landing
  points.
- LLM eval harness — plan-worthy the day plan 025's first paper sessions
  produce records; build it against real session logs (forward-capsule
  doctrine above).
- Article reader Grok pilot — operates plan 018's `x_article_queue`;
  needs maintainer's native X access, so it is ops + a short runbook, not
  autonomous build work.
- Broker adapter (Phase 2, human checkpoint 6).

## Findings considered and rejected

- **Empty doc stubs**: resolved 2026-07-08 — `docs/mandate.md`,
  `docs/risk_policy.md`, `docs/source_policy.md` written by the maintainer
  in a working session.
- **Theme concentration rule**: un-rejected 2026-07-08 — mechanism decided
  (primary theme, 60%); implemented by plans 001 + 003.
- **Sizing adjustment** (`adjusted_final_target_weight`): still deferred —
  needs inputs (thesis-quality scoring, liquidity data) that don't exist;
  plan 003 removes the dead field.
- **Untracked implementation**: resolved — baseline committed `01193d1`.
- **Spec §12/§15 reconciliation**: resolved 2026-07-18 in
  `boustrategy_spec.md` v0.2.

## Not audited (2026-06-12 run)

- `.agents/` (vendored skill files) and `scratchpad/` (gitignored).
- Dependency vulnerability scan: not run (sole runtime dep was pydantic;
  plan 007 adds yfinance — worth a `pip-audit` once deps grow).

## Public product planning, September 5, 2026

The public dashboard is no longer deferred: the handoff-based initial UI exists in the working tree.
The maintainer requested a full reevaluation of design/functionality gaps and real-app behavior,
and selected live portfolios as primary with paper results clearly separate. There is one live
account now; keep portfolio/agent identity modular for future views, without a dual-agent UI.
Existing strategy documents describe current choices; plan 031 proposes alternatives without
changing trading behavior or those documents. Its six phases form one self-contained product plan.

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 031 | [Complete the public live-agent product](031-public-live-product-plan.md) | P1 | L, phased | Existing public UI and live/run stores; verify working-tree signatures | COMPLETE in uncommitted main (audit and assessment complete; activation/pages deferred) |

Recommended order: identity/publication/scalable reads first; accounting, trace/policy records and
runtime/scheduling next; public pages from those contracts; finish the cross-system release matrix.
Preserve earlier plans and completion history. This section supersedes earlier public-deferral and
dual-account assumptions for the new public product only.

Considered and rejected: copying mockup thresholds without strategy rationale; confidence-based
human approval; inferring running from PREPARED; countdown from disabled-task NextRunTime;
treating deposits as gains; raw logs/account IDs; comparison leaderboard for one account.


Plan 031 completed September 8, 2026: six product phases plus the whole-codebase audit,
focused refactor and final operating assessment are integrated in uncommitted main.
Verification: 506 Python tests, 26 React tests and all lint/format/type/build/diff gates.
The final 100,000-record HTTP benchmark passed the latency/read-isolation targets.
See [audit findings and limits](../docs/plan-031-audit.md) and
[execution/scheduling/private-dashboard recommendation](../docs/execution-assessment.md).
No source database write, task/model/broker activation, real publication, commit or deployment occurred.
Private runtime controls, fresh collectors/reconciliation and staged activation are separate
follow-up work; additional public pages remain bookmarked.
