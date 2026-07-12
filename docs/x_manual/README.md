# Manual X Run — Week 1

Decided 2026-07-12: a 1-week manual curation run (timed to an earnings-dense
week) before building automated ingestion. You are the ingestion layer:
15 minutes a day, skim your curated handles, log the 5-15 most
decision-relevant posts into `log.jsonl` (one JSON object per line).

What this week produces:

1. Ground truth for the automated feed: after ingestion is built, replaying
   this week measures what the pipeline would have caught vs what you caught.
2. The first real entries in the account scrutiny ledger.
3. A measured baseline: how many useful posts/day actually exist across your
   handles, which sets the X API spend expectation against the $20/month cap.

## Curated handles (human-only, fill in before day 1)

Per `docs/source_policy.md`, curation is maintainer-only. List the handles
you are skimming this week (full account records per spec §8 can come later;
a plain list is enough for week 1):

- @
- @
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
