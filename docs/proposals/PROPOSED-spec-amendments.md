# PROPOSAL — Spec v0.2 amendments

> **STATUS: DRAFT PROPOSAL, NOT IN EFFECT.** Drafted by Claude 2026-07-15.
> `boustrategy_spec.md` is the maintainer's vision document; this file
> lists the exact section-by-section amendments needed to bring it in line
> with every decision made since 2026-07-08. Written as amendments (not a
> full rewrite) so review means reading ~2 pages, not re-reading 700
> lines. Apply by editing the spec per each item (or tell Claude to apply
> approved items verbatim), then bump the spec version note to v0.2.

---

## §0 Notes — version line

Change spec version to v0.2; add: "v0.2 (2026-07): reconciled with trial
findings and maintainer decisions; strategy docs in docs/ take precedence
where they overlap."

## §3 In-scope — one line

"Codex powered reasoning worker where possible" → "LLM work runs through
subscription agent sessions (Codex/Claude goal mode), not per-token APIs,
until economics or unattended-operation needs dictate otherwise (decided
2026-07-15)."

## §5 Regime model — mark the v0 input subset

Keep the input list but annotate: **v0 computes**: QQQ/SPY/SMH trend,
AI-leader relative strength (price cache), news reaction + AI capex
outlook + curated X narrative health (daily digest), calendar context
(events feed, when built). **Deferred until data exists**: breadth,
volatility/liquidity pressure, portfolio drawdown, hit rate (the last two
require live trading history). The regime JSON's `scores` object includes
only computable inputs per version.

## §6/§7 Data & source policy — three updates

1. X access: official API pay-per-use is the system of record; measured
   cost at trial scale ~$20-38/month conservative counting; budget guard
   in code (`MAX_MONTHLY_POST_READS`), recalibrated from real billing.
2. Price fallback order decided: yfinance → Massive → Alpha Vantage.
3. Paywalled newsletters (Citrini, SemiAnalysis, ...) approved as internal
   reference via maintainer subscriptions; never republished (private
   archive doctrine).

## §8 Curated X graph — replace the tier design and signal object framing

1. **Single tier, full fetch** (decided 2026-07-15, supersedes core/scan
   split): target ~50 accounts total, all full-timeline fetched, no
   keyword filtering anywhere. Selection criterion includes on-topic
   density; new accounts enter on probation and are auditioned by
   measured positive-rate before permanence. Accepted cost: ~$50-90/month
   at full size.
2. **Two-level signal model** (replaces the single aggregate X-signal
   object): level 1 = per-post captured signals (implemented:
   CapturedSignal — claim, claim_type, stance, horizon, scrutiny_verdict,
   primary_theme_id); level 2 = daily digest aggregating level 1 into
   theme-level narrative state (velocity, disagreement, crowding) for the
   reasoning chain. The account scrutiny ledger accrues from level-1
   verdicts (reduce-only vs human priors).

## §9 Triggers — simplify (decided 2026-07-15)

Replace the 0-20 numeric scoring rubric and thresholds with: v0 triggers
are (a) price/volume thresholds on holdings/watchlist, (b) calendar
events (earnings, FOMC), (c) flags surfaced by the daily digest.
Classification (NOISE/MONITOR/REVIEW/EXTRAORDINARY_OPPORTUNITY) is a
reasoning-layer judgment recorded with justification, not a point sum.
The hard gates survive as written (no extraordinary without causal link,
investable expression, belief mapping, fresh data). Revisit numeric
scoring only if judgment-based classification proves inconsistent in
evals.

## §12 Policy engine — update the limits table

- Max stock target weight 20%, max ETF 50% — unchanged, but apply to
  BUY/ADD only (holding/trimming an appreciated position is never blocked).
- Max holdings: 10 hard (was 3-6); ~7 goal lives in risk posture.
- Trade limits: BUY/ADD 2/day; TRIM/SELL never quota-blocked, 10/day
  circuit breaker as malfunction brake (was: unified 2/day).
- RED regime: BUY/ADD rejected unless the record declares
  extraordinary_opportunity with written justification (was: flat ban).
- New: single primary theme ≤ 60% of portfolio (per-decision
  primary_theme_id).
- New: minimum initial position 5% (posture-enforced, not policy).
- Sizing adjustment (downsizing instead of rejecting): still deferred;
  the field returns when inputs exist.

## §13 Architecture — interface reality

"Investment Intelligence MCP/API" → "Investment intelligence library +
CLI (implemented). Reasoning sessions interact via CLI and files through
the paper period (decided 2026-07-15); an MCP wrapper over the same
library is a pending decision, with the recorded lean that physical
containment (enforced no-direct-LLM-to-order) becomes a go-live
prerequisite." Decision statuses: implemented as specced through
order_intent_created; broker statuses arrive with the adapter.

## §15 Docs & cost — two updates

1. Static docs list: mandate/risk_policy/source_policy/decision_record
   exist (docs/); add risk_posture.md (tunable appetite layer, hybrid
   risk-split decision 2026-07-15); theme files still to write.
2. Cost buckets: X/social ~$50-90/month at full 50-account graph
   (accepted 2026-07-15); LLM via subscriptions; total ops ceiling
   unchanged at ~$100/month.

## §16 Build plan — status annotation

Phase 0 (schemas): done for decision record, order intent, X signals;
remaining schemas arrive with their features. Phase 1 (local records, no
broker): in progress — storage/state machine/price cache/X ingestion
done; reasoning layer next. Phase 3 items (curated X tracking, evals
groundwork) partially pulled forward by the trial.

## §17 Open questions — prune

Resolved since v0.1: curated account list (live roster + audition
process), initial position/order limits (decided set), GREEN/YELLOW/RED
thresholds partially (exposure bands live in risk posture; scoring inputs
v0 subset declared). Still open: exact reasoning prompts, daily chain
timing, backend broker-phase details, MCP decision.
