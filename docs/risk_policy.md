# Risk policy (7/8/2026)

Two layers: 

**Policy-enforced** limits are deterministic code in `app/policy/` and cannot be reasoned around. 

**Mandate-enforced** rules are obligations on the reasoning agent,
enforced through prompts, records, and evals.

## Policy-enforced hard limits

| Limit | Value | Applies to |
|---|---|---|
| Max stock target weight | 20% | BUY/ADD only (holding or trimming an appreciated position is never blocked) |
| Max ETF target weight | 50% | BUY/ADD only |
| Max single primary theme | 60% of portfolio | BUY/ADD, computed on `primary_theme_id` |
| Max holdings | 10 (goal of ~7 lives in the mandate, not policy) | BUY of a new position |
| BUY/ADD trades per day | 2 | BUY/ADD only |
| TRIM/SELL circuit breaker | 10 per day | Malfunction brake only; de-risking is never quota-blocked by design |
| RED regime / de-risking mode | BUY/ADD rejected unless `extraordinary_opportunity` is declared with written justification | Escalation gate, not a ban |
| Actionable decisions | Require refined thesis, invalidation criteria, source claims, strategy belief mapping | Schema + policy |

## Extraordinary opportunities

- Full normal sizing caps apply (20%/50%): a trade that truly clears the
  extraordinary bar deserves real size, in any regime.
- The escalation is auditable by design: flag plus written justification on
  the record, visible on the dashboard.
- **Tracked metric**: how often the extraordinary bar is cleared, and the
  outcome quality of those trades. The bar is intended to be rare. If evals
  show the flag becoming a rubber stamp, tighten here (e.g. require a
  matching trigger classification). If they show consistently excellent
  reasoning, the maintainer intends to expand extraordinary positioning.

## Mandate-enforced rules (see mandate.md)

- Minimum initial position 5%; conviction tiers govern sizing.
- Invalidation hit = mandatory same-day review; at most one re-underwrite
  per position, then exit.
- Single position down 40% from entry = same mandatory review, regardless of
  whether written criteria technically hold.

## Drawdown doctrine: regime model governs

There is **no portfolio-level drawdown trigger**. De-risking is driven by
the GREEN/YELLOW/RED regime model alone. Severe drawdowns inside the
framework are acceptable by design; mechanically selling bottoms because a
threshold tripped is the classic way disciplined systems lock in the worst
outcome.

**Acknowledged risk (recorded deliberately):** this makes the regime scorer
a single point of failure. If the regime model is broken, lagging, or fed
bad data, nothing mechanical catches a bleeding portfolio. The compensating
controls are human and asynchronous:

1. The public dashboard (planned): the human will monitors portfolio health,
   drawdown, and regime state visually.
2. LLM evals on past trades (planned): periodic review of decision quality,
   including whether regime calls tracked reality.
3. The human iterates on the harness when these reveal problems.

Until the dashboard and evals exist, a broken regime model can silently bleed. A future option that stays inside this doctrine: drawdown thresholds that only flag records and notify the human on the dashboard, with no forced selling.

## Execution risk

- Default to limit orders. Market orders only for liquid names with tight
  spreads, small notional, normal market conditions, not near open/close.
- No order exists without an approved decision record passing schema
  validation and policy checks (no direct LLM-to-order path).
- Idempotency: every workflow carries stable IDs. after a crash, resume from
  the last safe state rather than risking duplicate orders.
