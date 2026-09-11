# Plan 040: Make scheduled reviews research and hunt like the 2026-08-26 session

## Status

- **Priority**: P0 · **Effort**: M · **Risk**: MEDIUM (changes live review behavior)
- **Depends on**: plan 039 launch finishes first (maintainer order, 2026-09-11)
- **Planned at**: commit `182df87`, 2026-09-11

## Why

The only reasoning that produced trades (2026-08-26: NVDA and TSM BUYs, META PASS) was an
interactive session. Its first pass also said "no action"; it traded only after the operator
reopened it for active research.

The scheduled runtime (`54655fa`, `0349951`, 2026-09-08) was built as a transcription step:
"author records from the provided intake only". It is one turn, read-only, schema-bound and
started with `--ignore-user-config`, so no reasoning effort is set. Empty output is explicitly
valid, nothing checks that it hunted, and no operator pushes back. `3e9ebad` (09-10) permitted
search in one paragraph. Every live review since has ended NO_ACTION on 26-241 reasoning tokens,
and none hunted despite 0% invested in GREEN.

**Tools are not the gap.** A probe on 2026-09-11 used the runner's exact flags plus high effort.
`gpt-5.6-sol`'s built-in web tool:

- opened live quote pages (NVDA and TSM Cboe real-time at 13:05 ET);
- opened NVIDIA's primary Q2 FY27 release;
- opened the 10-Q document on SEC EDGAR.

Its dedicated finance-quote endpoint returned nothing, but opened quote pages worked. The
missing pieces are effort, instructions, candidates and enforcement.

## Target behavior (maintainer direction, 2026-09-11)

1. Research by default, every review, with the model's own web tools.
2. Always hunt: rank viable candidates, research each, then act or put it away as WATCHLIST or
   PASS against our metrics.
3. High reasoning effort.
4. Primary sources opened and cited, and prices read from an opened live quote page with its
   timestamp.

Deterministic market data (quotes, SEC, fetch logging) is deferred to a later plan.

## Invariants (unchanged)

- The authoring session keeps `--ignore-user-config`, a read-only sandbox, and no broker MCP,
  database or writable files.
- The trusted worker still validates schema and policy. The broker preflight still enforces the
  entry price band at execution.

## Steps

1. **High effort.** The authoring runner passes `-c model_reasoning_effort="high"` explicitly.
   Record reasoning and output tokens, search and open counts, and duration for each attempt
   (from `events.jsonl`).

2. **Research-first authoring contract.** Rewrite `_AUTHORING_CONTRACT`:
   - research is the default;
   - open primary sources (company IR, SEC EDGAR, exchange or regulator) rather than cite snippets;
   - read each price from an opened quote page and cite its URL and display time;
   - empty output is valid only when the hunt is recorded.

3. **Candidate list in the intake.** Prep adds a ranked "Candidates to research" section:
   - current holdings;
   - tickers from significant digest items (cashtags plus a company-to-ticker map);
   - the maintained watch universe, with the reason each is listed.

   Add an explicit exposure line: "Invested X% vs REGIME target A-B%: below band, hunt
   required". Expire `digest_headline` triggers after 3 sessions (85 pending today).

4. **Hunt enforced by schema.** Add a required `candidates_considered` block: ticker, idea
   source, sources opened, outcome (BUY/ADD/WATCHLIST/PASS), reason.
   - When invested exposure is below the regime band, the worker requires at least 3 candidates
     researched.
   - Each non-BUY outcome is saved as a WATCHLIST or PASS decision record, which puts it away
     visibly.
   - Output that skips the hunt is rejected and retried once, then the run fails loudly instead
     of recording NO_ACTION.

5. **Doctrine alignment (maintainer-owned; drafted for approval).**
   - `daily_management.md`: "no action should be the result on most days" applies only when
     exposure is inside the band. Below it, the hunt in step 4 is mandatory.
   - `thesis_chain.md`: add step 0, candidate selection and ranking.

6. **Validation before live.**
   - Replay the 2026-08-26 intake through the new runtime in dry-run (no submit). Expect NVDA
     and TSM researched from primary sources, with reasoning comparable to the manual session.
   - Run one shadow review on a current intake (dry-run).
   - Maintainer reviews both, then enable for live.
   - For two weeks, watch candidates per run, opens, rejects, tokens, cost and outcomes.

## Done criteria

- [ ] Reviews run at high effort and show opened primary sources and quote pages.
- [ ] Below the band, at least 3 candidates are researched. Each ends BUY/ADD, WATCHLIST or PASS
      with a recorded reason. No silent NO_ACTION.
- [ ] Every BUY/ADD entry bound cites an opened quote page and its timestamp.
- [ ] The authoring session still cannot reach the broker MCP (test).
- [ ] 08-26 replay and one shadow run approved by the maintainer before live enablement.

## Decisions needed

- **D2 doctrine wording**: approve the step 5 edits when drafted.
- **D3 numbers**: 3 candidates below the band, trigger expiry after 3 sessions (proposed).

## Later plan

Deterministic market data: official quote API, SEC EDGAR client, a logged fetch tool that lets the
worker verify citations, and code-supplied prices in the intake.
