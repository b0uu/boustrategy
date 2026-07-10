# Source policy

This document defines what counts as evidence, how claims are scrutinized, and the doctrine for the curated X feed, which is this project's intended differentiator.

## Sources: two kinds of trust

Allowed source types (enforced as a schema enum): `SEC`, `COMPANY_IR`,
`NEWS`, `X`, `PRICE_DATA`, `MACRO`, `ETF_ISSUER`, `INTERNAL_MEMO`.

Every source makes two kinds of claims: claims of fact (number, event did or did not happen, price) and claims of meaning (what it implies, the narrative).

These are different types of trust (factual reliability vs opinion quality).

Factual reliability prior: mechanical records (SEC filings, official macro
data, price/volume) > company IR numbers > reputable news facts > X claims.

This ranks provenance: how likely the raw facts are real. X claims of fact start unverified and must be substantiated before use.

Interpretation should never be solely trusted by rank. No source class earns narrative trust automatically: IR framing is spin around accurate numbers, news framing is consensus by construction, price carries no narrative until a reader supplies one, and X framing is where both differentiated insight and confident nonsense live. Every claim of meaning, from any source, earns trust only through the expert-reader doctrine below.

Practical rule: use high-provenance sources to establish what is true. Use narrative sources to find what it means before others do. Never let a source's factual authority launder its narrative: "the filing says X" and "the filing means Y" are different claims, and only the first inherits the filing's trust.

## The reliability rule

Every source used in a decision record must be timestamped and classified. If freshness, reliability, or access is insufficient for the claim being made, downgrade the signal to MONITOR/REVIEW or refuse to create an order intent.

## Claim scrutiny: (expert-reader doctrine)

The agent's job when reading any source, especially X, is to be the domain
expert who notices what's wrong, not the average reader who is impressed.
(Motivating intuition: an expert reading a news article about their own
field sees all the flaws, then forgets that lesson reading the next
article. Do not have that flaw, you are an expert in every field and know when someone doesn't truly know what they are talking about.)

For every claim that supports a decision:

- Check substance against mechanism: does the claim make technical,
  physical, financial sense? A supposed semiconductor expert talking
  confidently about semiconductors must be checked on the substance, not
  believed on the confidence. Call out specifically when someone does not
  know what they are talking about.
- Require real evidence: claims must be supported by something observable
  (data in the post itself, filings, prices, verifiable events), not by
  the author's follower count, engagement, or tone.
- `confirmed_outside_x` on a record means exactly this: the X-derived
  claims were substantiated by real evidence and survived expert scrutiny.
  It does not merely mean "another outlet repeated it".
- Counter-evidence is part of the read: actively look for the strongest
  reason the claim is wrong before using it.

## Counter-evidence discipline

Scrutiny must not become a thesis veto. Anyone motivated enough can conjure counter-evidence against any thesis, and great theses attract the most scrutiny. Visible objections are exactly what keep consensus from pricing them.
The presence of counter-evidence is expected, not disqualifying. A thesis
with no credible objections is probably consensus.

Rules:

- Symmetric scrutiny: counter-evidence faces the same expert-reader bar as
  supporting evidence. A counter-claim also needs a mechanism and observable
  support. "It might be priced in" with nothing behind it is vibes, not
  counter-evidence.
- Materiality: to kill a thesis, counter-evidence must break a load-bearing
  pillar (ideally one named in the invalidation criteria). Chipping at
  peripheral details can lower confidence but cannot kill.
- Refute vs reprice: most counter-evidence does not refute, it resizes.
  Non-fatal counter-evidence moves the conviction tier down, tightens
  invalidation criteria, or delays entry. Only mechanism-breaking
  counter-evidence justifies rejecting the idea outright.
- Pre-committed standards: the thesis declares its invalidation criteria up
  front; counter-review judges against those, not against new standards
  invented mid-review.
- Tracked metric: how often the counter-thesis step kills ideas that later
  prove right. A rising kill rate on winners means scrutiny is neutering
  boldness and needs recalibration.

## Recency doctrine:

There are no fixed recency cutoffs. The age of a signal is weighed against the
claim's horizon:

- A tweet seen within seconds carrying short-term implications can be pure
  alpha; the same tweet a day later (or even hours, minutes) may be fully priced.
- A weeks-old post with long-term structural implications (capacity,
  regulation, architecture shifts) can still carry real edge if the market
  has not absorbed it. Especially to use for thesis building and invalidation

The required reasoning on every aged signal: given this signal's age and
horizon, has the market already priced it? Stale short-horizon signals
that you may be late, and recency raises urgency.

## The curated X feed

Purpose: detect narrative velocity, disagreement, crowding, and early
themes before they are consensus (SB-005). The feed exists to make the
agent bolder earlier, with scrutiny as the safety mechanism.

Rules:

- X may serve as idea source, confirmation, counter-thesis, or crowding
  warning. X sentiment alone never authorizes a trade: every X-derived
  claim must pass the expert-reader doctrine above.
- Skeptics and counter-thesis accounts are first-class citizens of the
  graph, not noise to filter out.
- **Curation is human-only.** The maintainer alone adds and removes accounts. The agent consumes the graph and may report on
  account quality (early calls, specificity, hit rate), but proposes neo
  changes and makes none. The graph is versioned; every change is logged.
- Account scoring dimensions: early theme detection, specificity,
  source quality, primary-source alignment, counter-evidence handling,
  early-vs-late tendency, hype/pump behavior.

## Account scrutiny ledger

Every time the expert-reader doctrine runs on an X claim, the verdict is
recorded against the account: handle, topic, claim, verdict (substantiated,
unsupported, wrong, nonsense), and the decision it fed. Each account
accumulates a scrutiny history over time.

- Weight follows history: an account that repeatedly survives scrutiny on a
  topic earns weight there; a confidently uninformed account loses it.
- History is topic-scoped. Expertise on semiconductors says nothing about
  the same account's macro takes; weight is earned and lost per topic.
- The ledger only reduces influence. The agent's observed score can lower
  an account's effective weight below the human-set prior and max signal
  weight, never raise it above them. Membership and priors remain
  human-only: the ledger is evidence for the maintainer's curation
  decisions, not a mechanism that edits the graph.
- Recent scrutiny counts more than old scrutiny (people improve and decay).
  One bad call does not zero an account; a pattern does.
- Where a claim resolves checkably true or false later, the resolution is
  added to the ledger. Early-and-right is the most valuable pattern;
  confident-and-wrong is the most damning.

## X ingestion: decided approach

The ingestion layer is designed **source-agnostic** (curated handle list +
the X signal object schema from spec 8), with the provider decision
deferred to a dedicated cost/feasibility research pass. 

Candidates: official X API tiers, Grok API live search, third-party providers, or a manual
curation MVP. The spec's $10-30/month budget for X tracking is likely
optimistic against official API pricing; the research pass settles this
before any build commits to a provider.

## Public safety

Every source claim carries a `public_safe` flag. The public dashboard shows
only claims marked safe; internal notes and non-redistributable content stay
private. When in doubt, mark it private.
