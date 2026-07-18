# Gate Experiment: Findings

2026-07-15 → 2026-07-17. Predictor: gpt-5.6-luna (subscription goal-mode
session, no API). Data: 1,761 human-labeled trial posts. Artifacts:
`data/gate_experiment/` (batches, predictions, reports), adjudications in
`x_adjudications`.

## Purpose

Before automating the relevance gate (the cheap filter deciding which X
posts deserve the reasoning agent's attention), measure whether an LLM can
reproduce the maintainer's significance bar — and map exactly where it
diverges. Secondary purpose, which proved equally valuable: stress-test
the human labels themselves, since the maintainer labeled 1,761 posts at
speed and acknowledged fallibility.

## Method (summary)

1. All 1,761 labeled posts exported blind (no labels) in 36 JSONL batches
   with a distilled rubric.
2. A Luna goal-mode session judged every post cold: significant/skip.
3. Predictions ingested and scored against human labels.
4. All 485 disagreements triaged: 42 article-pattern posts auto-upheld by
   doctrine; a second independent model reviewed the remaining 428 and
   recommended verdicts; Claude (Fable) hand-verified a 25-post sample of
   its overturn calls (~88% agreement); the maintainer approved bulk
   application. 122 upholds and 221 label corrections applied — every
   correction stores the original label and is reversible in the
   adjudication UI. 85 borderline/unsure remain optionally pending.

## Results

| Metric | Raw | Corrected ground truth |
|---|---|---|
| Agreement | 72.6% | **85.2%** |
| Precision (positive) | 0.786 | **0.907** |
| Recall (positive) | 0.771 | **0.860** |

Raw agreement excluding the article cluster (posts whose content the API
cannot deliver): 74.3%. The 12.6-point raw→corrected jump is entirely
human label errors being fixed, not grading generosity.

## Findings

1. **The curated feed is ~64% signal.** A binary gate over a well-curated
   roster filters little; the real downstream need is ranking/digest, not
   noise removal. (This finding reshaped the roadmap: daily digest over
   gate-as-bouncer.)
2. **The article gap is the largest structural blind spot.** 59 link-only
   article posts, 76% positive — the feed's highest value-density class —
   are invisible to the API (read endpoints don't exist). Rule adopted:
   link-only posts from roster accounts are NEVER auto-skipped; they
   route to an article queue (human or Grok-pilot reader).
3. **The model under-used reply context.** The largest model-error
   cluster: judging a reply's own terse text while ignoring the
   substantive parent supplied alongside it. Rubric v2 must demand
   context-inclusive judgment explicitly.
4. **Human error was systematic, not random**: (a) mass-skipped account
   blocks during fatigue (missed a Getty–OpenAI deal that moved GETY
   150%+, an AI physics-olympiad gold, a confirmed CPO supply-chain
   delay); (b) non-English posts skipped at the language barrier that the
   model read natively (Korean/Chinese supply-chain and legal facts); (c)
   a generous streak on favorite accounts (banter labeled significant).
5. **Media posts were EASIER than text (86% vs 69% raw agreement)** —
   charts wear their substance openly. The feared image-blindness mostly
   didn't materialize once media URLs were attached.
6. **Difficulty maps to account type**: formulaic accounts near-perfect
   (arfurgrok 100%, kobeissiletter 95%); taste-heavy commentary and
   research-significance accounts hardest (evrgn 49%, ch402 55% raw).
7. **One nuance the next rubric must carry**: coy insider posts (a wink
   under a leak from a known insider account) read as contentless to a
   literal judge but ARE signal given the account's roster role.
8. Caveat: the human bar itself drifted mid-trial (capability-signal rule
   and three-tier flow arrived mid-week), so raw agreement understates
   the model; corrected agreement is the honest number.

## Conclusion

At 85.2% corrected agreement / 0.907 precision / 0.860 recall — with the
article class handled by routing rule rather than judgment, and the two
main model weaknesses (reply-context underuse, insider-wink nuance) being
promptable fixes — **the gate is good enough to hand the daily labeling
loop to a subscription agent session**, with the maintainer auditing by
exception rather than labeling by default. Equally important: the
experiment doubled as an audit of the ground truth itself and corrected
221 labels, which materially improves everything trained or evaluated on
this dataset. The methodology (blind export → independent judge →
triage → sampled verification → audited bulk correction) is reusable as
the template for every future capability handover in this project.
