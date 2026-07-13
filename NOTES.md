# Overall notes

My personal notes that will help agents understand my vision and align the project with my thoughts. Will also help address gaps or contradictions in my thoughts.

**Contract for agents reading this file**: this is thinking, NOT doctrine.
Where anything here conflicts with `docs/mandate.md`, `docs/risk_policy.md`,
`docs/source_policy.md`, or `boustrategy_spec.md`, those win. Nothing here
is an instruction to execute. It IS useful context for understanding where
the maintainer's head is.

**Review loop**: write freely below. Tag anything you want checked:

- `[?]` — verify this understanding / is this sound?
- `[idea]` — half-formed idea, poke holes or develop it
- `[todo]` — thing I don't want to forget

Ask to "review my notes" and verdicts and suggestions get appended
under each tagged item as a dated `> review:` block

---

## Current snapshot (2026-07-12, delete when stale)

- Plans 001-011 all DONE. Backbone + X trial stack + labeling UI live on main.
- Trial blocked only on me: token (`setx X_BEARER_TOKEN`), finalize wk1
  roster, then daily fetch → review at 127.0.0.1:8377 → status.
- Carrying items: theme memos (14), skeptic/short-seller seat still empty,
  budget recalibration after trial, spec §12 reconciliation (15 min),
  relevance-gate plan gets written FROM trial labels.

---

## Notes

- I'm thinking that the differentiating factors for this agent are the following:
  - Feeding agent a live, curated X feed (automatically), either inciting the agent to take action, or for the agent to refer to and bounce off of while making its  decisions based off other evidence
  - Manually feeding the agent a curated set of opinions, theses, research papers, articles, even tweets, etc. I feel like this data should be weighed more heavily narrative-wise than any automatic source of information. The agent will hold this in long-term memory, and dynamically adjust this memory when it comes across new supplementing or contradictory information
  - I think in the future, after successfuly implementing a solid live curated X feed pipeline, I should add additional live feeds of even more reputable sources and opinions (for example a live, curated/filtered feed of newly published research in specific areas). I chose X initially because it truly does cover almost everything if you pick the right accounts, but adding this can add a lot more nuance and consistency imo.

> review (2026-07-12): all three sound and mutually consistent. (1) Built,
> trial pending. (2) This is your spec's INTERNAL_MEMO source type grown
> into a real system — two guardrails when it gets designed: high prior
> must not mean exemption (your counter-evidence discipline has to apply
> to YOUR memos too, or this becomes a confirmation machine that flatters
> your priors); and "dynamically adjust memory" should be an append-only
> annotation layer — the agent attaches supporting/contradicting evidence
> and a freshness marker to each memo but never edits your text. Same
> reduce-only pattern as the scrutiny ledger, preserves human-only
> curation. Name for the future plan: "curated corpus + annotation
> ledger". (3) The ingestion layer was deliberately built source-agnostic,
> so a curated research feed is a new fetcher + the same cascade + a new
> source type — cheap when you're ready (arXiv RSS is free). X-first
> sequencing is right: prove the pipeline on the hardest, noisiest source.
- I'm also thinking that the boring part of the agent should still be rock solid:
  - Agent should be up to date on all extremely relevant news (ex: earnings, hourly/minute price, upcoming federal events, geopolitical news) without manual intervention. Manual intervention should be purely supplemental, the agent should be able to be proficient without.
  - I'm thinking for stuff like live geopolitical news we follow 1-2 reputable and consistent sources to fulfill the standard.
  - I know that I planned to make the agent reactive to big news, but I'm not sure how costly it would be to do that. I also know that I planned to run the investment reasoning process X amount of times per day, and I also am not sure whether that is the way to ago. Need to review architecture again to really get a feel of what to do next
  - I'm also thinking that we should expand from 

> review (2026-07-12): mostly sound, two corrections and one pointer.
> (1) "hourly/minute price" — nothing in the harness acts intraday (one
> daily chain, rare thesis chains), so minute-level data would be paid for
> and never consumed. Daily bars + an events calendar (earnings dates for
> holdings/watchlist, FOMC schedule — free sources, fully autonomous)
> cover the "rock solid boring" standard for v0.1; intraday data earns its
> cost only when intraday triggers exist. Added an events-calendar item to
> the direction list. Geopolitical via 1-2 reputable feeds: sound, maps to
> the NEWS source type and the same cascade.
> (2) Reactive-to-news cost — your spec already solved this and it holds
> up: the trigger system (§9) IS the cost control. Cheap classification
> runs constantly; expensive reasoning runs only when a trigger clears the
> NOISE/MONITOR/REVIEW thresholds. "Reactive" ≠ "reasoning continuously" —
> it means paying for exactly one deep run when something real happens.
> The scheduled daily chain and trigger-driven runs coexist by design.
> (3) Your last bullet cuts off mid-sentence ("expand from...") — finish
> the thought, it was heading somewhere.

- Some concerns:
  - I'm concerned about how costly it would be to truly build out my vision. Almost everything in a good investment decision pipeline is non-deterministic, so I would have to call LLMs for many, many actions. Especially with live feeds, where latency is a big factor, I would want to screen every single incoming item with a cheap model, and for each additional screening stage that an item passes, there is a deeper review with a smarter model that considers more and more context. And this would likely be ran many, many times daily, 24/7 if cost wasn't a barrier.
  - It's lowkey been a min since I created the initial architecture so I'm not sure how much of it holds up rn
  - I want to make good and effective evals, so I need to plan for that rather than adding it on as a side thought. I've already started planning, and I am planning on doing forward evals that take performance, look at the reasoning and compare it to desired result. Need to formalize more though

> review (2026-07-12): (1) Cost — your staged-screening instinct IS the
> decided cascade architecture, and the arithmetic is friendlier than you
> fear: cheap-model screening at trial volumes runs single-digit dollars
> per month (batched, ~100 tokens/post), and the expensive tail — full
> thesis chains — is rare BY DESIGN (0-1/day steady state per your own
> spec). The funnel narrowing is what makes the vision affordable. The
> only genuinely costly ambition is 24/7 sub-minute latency, and
> long-horizon equity theses rarely need it — let the trial and trigger
> thresholds prove faster reaction buys anything before paying for it.
> (2) The architecture holds up better than you think: the last month
> IMPLEMENTED your spec rather than replacing it (records/policy/intents/
> state machine = §11-13; the filter cascade = §9 generalized). Known
> stale: §12 limits, §15 X budget, §5 regime scoring unbuilt. A
> spec-vs-reality reconciliation pass producing an updated spec is ~30 min
> of agent work whenever you want it.
> (3) Evals — sound, and matches the forward-capsule decision. One
> sharpening: separate PROCESS evals (did the reasoning follow the
> mandate/doctrine — fast, actionable, run constantly) from OUTCOME evals
> (did it work — slow, noisy, used to calibrate the process rubrics), with
> your approved/rejected preference labels as the third leg. Formalize
> once the reasoning worker exists; the trial week is already banked as
> capsule #1.

- Some ideas:
  - Maybe have a price movement threshold that prompts checking (inspired by coinbase / robinhood mobile notifications), would be better than a random CRON job

> review (2026-07-12): sound, and it's already in your spec — this is the
> PRICE trigger type (§9). Threshold-crossing beats cron on
> reactivity-per-dollar precisely because it's the cascade's cheapest
> stage: a price check is free, and it only wakes expensive reasoning when
> something moved. One implementation note: detecting intraday moves needs
> intraday quotes — a cheap current-price poll a few times a day (or the
> broker quote endpoint in Phase 2), NOT minute-bar history. Belongs in
> the trigger-system build, which is the natural plan after the trial +
> relevance gate.
---

## Archive


