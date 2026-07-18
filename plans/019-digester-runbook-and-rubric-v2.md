# Plan 019: Digester session runbooks + gate rubric v2

> Executor instructions: follow exactly; verify each step; STOP on
> mismatch. Branch `advisor/019-digester-runbook`, do NOT push, don't
> touch plans/README.md. This plan creates documentation only — no code,
> no schema, no edits to maintainer-owned strategy docs
> (`docs/mandate.md`, `docs/risk_policy.md`, `docs/risk_posture.md`,
> `docs/source_policy.md`).

## Status

- Priority P1. Effort S. Depends on plan 018 (hard: the runbooks drive
  its CLI). Planned at local main `a97a85f`, 2026-07-18.

## Why this matters

Plan 018 builds the deterministic pipeline; this plan writes the
instructions the recurring subscription agent sessions follow to operate
it (maintainer decision 2026-07-15: subscription goal-mode sessions, not
per-token APIs). Deliverables are three documents under
`docs/x_pipeline/`: the judging rubric v2 (upgraded with the gate
experiment's findings), the intraday digester runbook, and the Sunday
weekly runbook. The rubric v2 content below is derived from
`docs/research/gate_experiment_findings.md` findings 1, 3, 6, 7 and the
plan 015 rubric v0.

## Current state (local main `a97a85f` + plan 018 merged)

- `docs/x_pipeline/` does not exist yet.
- Plan 018 provides: `python -m app.x.run cycle|route|digest-render|
  weekly-render`, run ledger, article auto-routing, rank vocabulary
  headline|notable|context, digest files at `data/digests/` with a
  preserved `<!-- synthesis:start/end -->` block.
- Plan 015's rubric v0 lives verbatim in
  `plans/015-gate-agreement-harness.md`; the experiment export dir has a
  copy. Its maintenance note designates it "the seed of the production
  gate prompt" — this plan is that iteration.

## Scope

IN (create): `docs/x_pipeline/RUBRIC.md`, `docs/x_pipeline/DIGESTER.md`,
`docs/x_pipeline/WEEKLY.md`.
OUT: everything else. No code. No scheduler installation (see the
maintainer ops note at the end). No reasoning/thesis prompts — those are
human checkpoint 5 and a different plan.

## RUBRIC.md (write this content, verbatim)

```markdown
# Gate rubric v2 (production digester standard)

Judge each exported post `significant` or `skip`; every significant post
also gets a `rank`. Judge from the FULL provided content: text, reply
context, and media. Opening media URLs to view images is expected, not
optional — charts and screenshots wear their substance openly.

Rules carried and upgraded from v0 + the gate experiment:

1. **Context-inclusive judgment (mandatory).** A terse reply under a
   substantive parent is judged on the CONVERSATION's substance, not the
   reply's own text. Ignoring supplied reply context was the largest
   model-error cluster in the experiment.
2. **Insider-wink rule.** A coy, low-content post (a wink, "big week",
   an emoji) from an account whose roster role is insider/leak coverage
   IS potential signal — rank it `context` with reason "insider-coy"
   rather than skipping. For all other accounts, coyness is noise.
3. **Non-English posts are first-class.** Read them natively; the
   human-era language barrier does not exist for you.
4. **No engagement signals.** Never weigh likes/reposts/virality; viral
   is late-consensus by doctrine.
5. **When torn between skip and significant, choose significant at rank
   `context`.** The roster runs ~64% signal; the digest ranks, it does
   not bounce. (This inverts v0's "when torn, skip", which was written
   for a filtering gate.)

significant = a substantive claim that could, even two steps removed,
change how an AI/tech/markets theme is scored, seed or kill a thesis, or
shift a regime input: capability advancements, research results,
supply-chain facts, capex/demand signals, credible skepticism,
market-structure observations. Tickers are NOT required.

skip = no articulable claim even with context: vibes, hype, jokes,
engagement bait, personal chatter, congratulation noise.

Link-only article posts never reach you (code routes them to the article
queue). If a post's only substance sits behind a link but it also has
its own articulable framing, judge the framing.

Ranks (required when significant):
- `headline` — could plausibly warrant a decision-record review this
  week: thesis-relevant new facts, regime-input moves, credible
  counter-evidence against a plausible holding. Expect 0-3 per run;
  a headline drought is normal, a headline flood means you're inflating.
- `notable` — moves a theme's evidence base; the reasoning agent should
  read it this week.
- `context` — background that sharpens the picture; skimmable.

Output one JSON line per post:
{"post_id": "...", "prediction": "significant"|"skip",
 "rank": "headline"|"notable"|"context" (significant only),
 "reason": "<=15 words"}
```

## DIGESTER.md (intraday runbook — write with this structure)

Steps the session follows, in order:

1. `python -m app.x.run cycle --slot <slot>` (slot from the schedule
   that launched you). If it prints a calendar no-op: stop, done.
2. Read every `batch_*.jsonl` in the run's export dir; judge per
   RUBRIC.md; write `predictions.jsonl` alongside.
3. `python -m app.x.run route --run <run_id> --predictor <session-name>
   --in <predictions.jsonl>`.
4. `python -m app.x.run digest-render --date <today>`.
5. Author the synthesis block (between the markers, which the renderer
   preserves): 3-8 sentences — what changed since the last run, which
   theses/themes the headline items touch, contradictions between
   sources, and what the article queue is still hiding. Plain claims
   with handles, no hype.
6. Close run only: read the whole day's digest once for coherence, then
   commit the day's digest + run artifacts
   (`git add data/digests data/x_runs && git commit`) — daily capsule
   discipline. Do NOT push (standing rule: push needs maintainer
   approval).
7. Escalations to note at the TOP of the synthesis block, never act on:
   fetch failures or a tripped budget guard ("BUDGET" line with
   remaining reads); any single run exporting > 150 posts (roster or
   API anomaly).

Hard prohibitions (print these verbatim in the doc):

- NEVER launch, or continue into, a reasoning/thesis/decision session.
  The ACTIONABLE marker is a flag for a different worker behind human
  checkpoint 5. This is a structural rule, not a judgment call.
- NEVER write `x_posts.review_status`, edit the roster/`x_accounts`, or
  edit anything under `docs/` except nothing — this runbook grants zero
  doc edits.
- NEVER exceed the budget guard by fetching manually.

## WEEKLY.md (Sunday runbook — write with this structure)

1. `python -m app.x.run cycle --slot weekly` then
   `python -m app.x.run weekly-render --date <today>`.
2. Author the weekly synthesis: narrative deltas across the week (what
   strengthened, what broke), per-theme rollup of headline/notable
   items, unresolved article-queue entries worth human attention,
   roster observations from the per-account table (audition candidates
   up or down — observations only; curation is human-only), open
   research questions, and Monday watch items (events calendar is a
   future plan; until then, note what the week's posts flag as
   upcoming). Note the next market session explicitly when Monday is a
   holiday.
3. Until the reasoning worker exists, the thesis-review section is the
   literal line "No active theses — reasoning worker not yet live."
   Never draft theses here.
4. Commit the weekly file (no push) — this is the sealed weekly capsule.

## Steps

1. Create the three docs per the specs above (RUBRIC.md verbatim;
   DIGESTER/WEEKLY structured as specified, prose polished).
2. Cross-check every CLI invocation against plan 018's implemented
   flags (STOP if any drifted).
3. No code gates apply (docs only); `git status --porcelain` clean
   after commit.

## STOP conditions

- Plan 018 is not merged, or its CLI surface differs from what the
  runbooks reference.
- You find yourself writing thesis/decision prompts or anything that
  consumes the ACTIONABLE flag.
- You find yourself editing any maintainer-owned strategy doc.

## Maintenance notes

- **Scheduling is a maintainer ops step, not part of this plan**: four
  recurring session launches (08:45 / 12:30 / 17:45 ET weekdays, 18:00
  ET Sunday) each pointed at the matching runbook — via Claude Code
  scheduled routines or Windows Task Scheduler. Because `cycle` is
  calendar-aware and no-ops safely, a naive every-day schedule is
  correct; half-day close runs need either a second 14:45 trigger or a
  scheduler that fires both (the extra fire no-ops harmlessly).
- **Drift eval**: after any rubric edit (and otherwise monthly), re-run
  the plan 015 harness — export the frozen trial set, judge with the
  current rubric + session model under a new predictor name, `score` —
  and compare against the 85.2% corrected baseline. The file format is
  the eval contract; a material drop blocks the rubric change.
- The digester session name used as `--predictor` should encode model +
  rubric version (e.g. `luna-rubric2`) so `x_route_decisions` stays
  analyzable across upgrades.
