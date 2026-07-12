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

- @jukan05 - [] - 
- @zephyr_z9 [] - 
- @tphuang - [] - 
- @mingchikuo - [] - 
- @bubbleboi - [] - in between the shitposting he has some meaningful insights on industry and seems to have domain knowledge
- @mweinbach - [] - 
- @0xBADB01E - [] - need to screen this guy more, but people seem to view his recent tweets as technically insightful and novel
- @synthwavedd - [] - potential openAI insider, very in touch with frontier model progress and competition
-  @ArfurGrok - [] - insider for frontier lab & company employment notifications
- @aaronp613 - [] - early news and rumors insider for apple, looks behind the scenes for early news and credible rumors in other notable companies as well
- @evrgn11112231 - [] - provides personal insights on large cap stocks, tech, semis, and AI
- @CharlesRollet1 - [] - tech reporter at Business Insider, provides some good inside scoops
- @alexeheath - [] - good reporting on the AI race, with focus on top companies and competition
- @aleabitoreddit - [] - very influential insights on AI and semi supply chains. likely has power to move market short-term in some areas. good analyses.
- @KobeissiLetter - [] - commentary on global capital markets & geopolitics
- @


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
| `scrutiny_verdict` | `substantiated` \| `unsupported` \| `wrong` \| `nonsense` | scrutiny ledger seed — judge the claim, not the confidence |
| `why_it_matters` | 1-2 sentences | the human judgment being captured |

Example line:

```json
{"entry_id": "xm_001", "captured_at": "2026-07-13T09:05:00-04:00", "post_url": "https://x.com/example/status/123", "handle": "@example", "posted_at": "2026-07-13T08:40:00-04:00", "primary_theme_id": "ai_semiconductors", "tickers": ["NVDA"], "claim": "CoWoS capacity allocations for 2027 are already oversubscribed per supply-chain checks.", "claim_type": "interpretation", "stance": "idea_source", "horizon": "medium", "scrutiny_verdict": "unsupported", "why_it_matters": "If substantiated by an IR statement or filing, extends the packaging-bottleneck thesis another year."}
```

## Rules for the week

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
