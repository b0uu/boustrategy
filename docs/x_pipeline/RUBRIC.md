# Gate rubric (production digester standard)

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
