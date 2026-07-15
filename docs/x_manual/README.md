# Curated X Handles + Signal Schema

> **Role change (2026-07-12)**: the manual skim week was superseded by a
> monitored internal trial (plan 010) — the system fetches everything from
> the core-tier handles and the maintainer reviews the fetched inbox via
> `python -m app.x.run review` instead of skimming X directly. This file
> remains load-bearing for two things: (1) the **curated handle list**
> below seeds the versioned account graph (`app.x.run seed` parses it),
> and (2) the **log entry schema** below is the basis for the
> `CapturedSignal` model used by the review flow. `log.jsonl` is retained
> for any ad-hoc manual captures made before the trial tooling lands.

What the trial week produces:

1. Labeled ground truth: captured signals AND skipped posts (skips are
   labeled negatives) for building the relevance gate afterward.
2. The first real entries in the account scrutiny ledger, plus per-account
   capture rates that assign core/scan tiers.
3. A measured cost baseline against the $20/month (4,000 reads) cap.

## Curated handles (human-only, fill in before day 1)

Per `docs/source_policy.md`, curation is maintainer-only. For week 1, each
handle needs only: the handle, 1-3 category tags (from spec §8: semis
specialist, AI infra specialist, data center/power, macro/liquidity,
growth/tech investor, skeptic/short seller, market structure/flows,
company-specific, news, general high-signal), and one line on why it earns
a slot — format: `@handle - [categories] - why included`. Full account
records (credibility priors, allowed uses) come when the versioned graph
store is built; this list seeds it.

Tip: put these handles in a private X List first; skimming one combined
feed is what makes 15 minutes/day realistic.

Scale note (2026-07-12): the full curated graph may grow to 50-100
accounts, but do NOT try to skim that many manually — cap the week-1 skim
set at ~15-25. The accounts you skim this week are the de-facto **core
tier** candidates for the two-tier ingestion architecture (core = full
timeline reads; scan = server-side keyword-filtered reads); this week's
per-account entry counts seed the tier assignment. Feel free to keep
adding accounts below beyond what you skim — tag the ones you're actually
skimming this week with `(wk1)`.

- @jukan05 - [semis, news] - translated Korean semis supply-chain intelligence: HBM/HBF, Samsung/SK Hynix/Micron dynamics, memory pricing; frequently early on memory-cycle news
- @zephyr_z9 - [semis, ai-infra] - anonymous China semis/compute analyst: domestic fab and equipment progress, China DC buildout, supply-chain names; useful counter-consensus window into China capability
- @tphuang - [ai-infra, high-signal] - long-form China tech ecosystem analysis (AI, semis, telecom); primary-source-driven takes on China competitiveness
- @mingchikuo - [semis, company:apple, news] - Ming-Chi Kuo, TF International Securities supply-chain analyst; Apple/consumer hardware demand, component order checks; long market-moving track record
* @bubbleboi - [semis, high-signal] - in between the shitposting he has some meaningful insights on industry and seems to have domain knowledge
* @mweinbach - [ai-infra, company:apple] - Max Weinbach, Creative Strategies analyst; AI hardware and on-device AI, Apple/Qualcomm/Samsung ecosystem notes
* @0xBADB01E - [semis, ai-infra] - need to screen this guy more, but people seem to view his recent tweets as technically insightful and novel
- @synthwavedd - [company:openai, high-signal] - potential openAI insider, very in touch with frontier model progress and competition
- @ArfurGrok - [news, company:frontier-labs] - insider for frontier lab & company employment notifications
- @aaronp613 - [company:apple, news] - early news and rumors insider for apple, looks behind the scenes for early news and credible rumors in other notable companies as well
- @evrgn11112231 - [investor, high-signal] - provides personal insights on large cap stocks, tech, semis, and AI
- @CharlesRollet1 - [news] - tech reporter at Business Insider, provides some good inside scoops
- @alexeheath - [news] - good reporting on the AI race, with focus on top companies and competition
* @aleabitoreddit - [semis, high-signal] - very influential insights on AI and semi supply chains. likely has power to move market short-term in some areas. good analyses.
- @KobeissiLetter - [macro-liquidity, news] - commentary on global capital markets & geopolitics
- @AndrewCurran_ - [news, high-signal] - good insights on AI, frontier labs and their models
* @danrobinson - [high-signal] - good engineer and paradigm researcher, very smart
- @mindmoon_108 - [semis] - korean semis engineer, good insights in korean
- @cwolferesearch - [high-signal] - researcher with good insights
- @ch402 - [company:anthropic, high-signal] - Chris Olah, Anthropic co-founder; mechanistic interpretability research; a window into frontier-lab research direction and capability trajectory rather than markets
* @zekramu - [high-signal] - very rambled thoughts from a software engineer, can be abrasive and/or off topic but i feel has some good thoughts
* @user_bin_roygbiv - [high-signal] - lots of thoughts on AI ecosystem, anon but seems in touch with the atmosphere
* @SemiAnalysis_ - [semis, dc-power, ai-infra] - good semiconductor analysis
* @__tinygrad__ - [ai-infra, company:tinygrad] - cool company that actually makes commentary on stuff
* @haydonryan - [high-signal] - dev that has random bits of commentary
- @dylan522p - [semis, dc-power, ai-infra] - Dylan Patel, SemiAnalysis; probably the most influential public analyst on AI datacenter/semis supply chains; caveat: so widely read that his takes price in fast. treat as a substance benchmark, not early signal

### Suggested additions (Claude, 2026-07-13 — pending your review)

These fill structural gaps in the graph. They use `*` bullets so `seed`
ignores them; **to approve one, change its `*` to `-`**; delete what you
don't want. Honest caveat: suggestions skew famous — big names carry more
late-consensus risk than your obscure picks, which is where the edge lives.
Vet each like any other account.

Skeptic / short seller (currently empty — your source policy calls
skeptics first-class citizens):

* @WallStCynic - [skeptic, macro-liquidity] - Jim Chanos; the highest-profile public skeptic of AI capex and datacenter economics; exactly the structural counter-thesis seat the graph lacks
* @edzitron - [skeptic] - Ed Zitron; aggressive AI business-model skeptic who digs into OpenAI/hyperscaler unit economics; often maximalist, so use for counter-thesis stress-testing rather than as a fact source
* @GaryMarcus - [skeptic] - AI capability skeptic (technical side, not markets); counterweight to frontier-lab hype narratives

Data center / power + semis research (dylan522p promoted to the active
list 2026-07-13):

* @Fabricated_Know - [semis, investor] - Doug O'Laughlin, Fabricated Knowledge; semiconductor-cycle investing analysis, good historical context
* @GavinSBaker - [investor, ai-infra, dc-power] - Gavin Baker, Atreides CIO; investor-grade takes on AI infra demand, power constraints, semis

Macro / liquidity depth (currently only KobeissiLetter):

* @LynAldenContact - [macro-liquidity] - Lyn Alden; rigorous macro and liquidity frameworks, low noise, primary-data-driven

Market structure / flows (currently empty — optional seat):

* @jam_croissant - [flows] - Cem Karsan; options-positioning and vol-flows commentary; dense and jargon-heavy — only worth the slot if flows context proves useful in the trial



## Log entry schema

One line per post in `log.jsonl`. Fields:

| Field | Values / format | Why |
|---|---|---|
| `entry_id` | `xm_001`, `xm_002`, ... | stable reference for evals |
| `captured_at` | ISO timestamp with timezone | when YOU saw it (recency doctrine needs this) |
| `post_url` | canonical x.com URL | attribution + rehydration key |
| `handle` | `@name` | scrutiny ledger key |
| `posted_at` | ISO timestamp with timezone | age vs horizon reasoning |
| `primary_theme_id` | one theme from the taxonomy | matches decision-record vocabulary |
| `tickers` | list, may be empty | investable expression |
| `claim` | one sentence: what is being asserted | the unit the expert-reader doctrine scrutinizes |
| `claim_type` | `fact` \| `interpretation` | the two kinds of trust (source policy) |
| `stance` | `idea_source` \| `confirmation` \| `counter_thesis` \| `crowding_warning` \| `theme_discovery` | matches XSignalUsageType + spec §8 |
| `horizon` | `short` \| `medium` \| `long` | recency doctrine input |
| `scrutiny_verdict` | `substantiated` \| `unsupported` \| `wrong` \| `nonsense` \| `cannot_assess` | scrutiny ledger seed — judge the claim, not the confidence; `cannot_assess` = beyond my expertise, ledger-neutral, queued for expert revisit |
| `why_it_matters` | 1-2 sentences | the human judgment being captured |

Example line:

```json
{"entry_id": "xm_001", "captured_at": "2026-07-13T09:05:00-04:00", "post_url": "https://x.com/example/status/123", "handle": "@example", "posted_at": "2026-07-13T08:40:00-04:00", "primary_theme_id": "ai_semiconductors", "tickers": ["NVDA"], "claim": "CoWoS capacity allocations for 2027 are already oversubscribed per supply-chain checks.", "claim_type": "interpretation", "stance": "idea_source", "horizon": "medium", "scrutiny_verdict": "unsupported", "why_it_matters": "If substantiated by an IR statement or filing, extends the packaging-bottleneck thesis another year."}
```

## Rules for the week

- Three-tier labeling (2026-07-14): **Skip (s)** = not relevant; **Significant (f)**
  = one-click positive, relevant to the framework but no detailed write-up —
  this is the fast default for gate-training coverage; **Capture (c)** = the
  full 13-field signal, reserved for ~1-3 exemplary posts/day whose claims
  should become teaching examples for the scrutiny prompts and the ledger.
- Capture is NOT limited to posts with direct financial implications.
  The bar is: could this, even two steps removed, change how a theme or
  regime input gets scored, or seed/kill a thesis? Capability
  advancements, model-performance commentary, and research direction all
  qualify when the claim has substance (tickers stay empty, stance is
  often theme_discovery, horizon medium/long). Vibes-only hype still gets
  skipped — the expert-reader bar applies to capability claims too.
  Skipping all capability news would train the future gate to filter out
  the earliest form of edge; don't.
- Cap at 15 entries/day; forcing entries on a quiet day pollutes the
  baseline. Zero-entry days are data too.
- Log counter-thesis and crowding posts with the same energy as bullish
  ones — skeptics are first-class citizens of the graph.
- `scrutiny_verdict` is your call at capture time; if a claim later resolves
  (earnings confirm/refute it), append a NEW line with the same `post_url`
  and the updated verdict rather than editing the old line (append-only,
  like every other record in this project).
- Do not paste full post text into the log — claim summaries + URL only.
  (Keeps the public-safety posture clean; the URL is the rehydration key.)
