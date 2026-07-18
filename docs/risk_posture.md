# Risk posture

This document is a tuneable risk layer. It is consumed by the
sizing stage of decision workflows and by prompts. As of right now, it never overrides
`risk_policy.md` (deterministic hard caps always bind above anything
here). The mandate.md governs how the agent thinks, while this risk_posture.md governs how much it bets. Dials here can be tuned at any
time by editing this file and logging the change below. Possible dashboard implementation in future.

## Current profile: AGGRESSIVE (2026-07-15)

### The core dial: EV over comfort

When calibrated analysis favors an uncomfortable option, you should still take it at the size that conviction warrants. Lower, 'safe' sizing that doesn't reflect level of conviction is a posture violation of the same severity as recklessness. Severe
drawdowns inside the framework are acceptable by design.

### Conviction tiers (BUY/ADD sizing)

Every BUY/ADD must place itself in a tier and defend that placement:

- **Starter (5-8%)**: good thesis, key evidence still developing. The tool
  for acting early while the variant perception is still being validated.
- **Core (10-15%)**: validated conviction. Initial thesis survived the
  counter-thesis, evidence has confirmed, regime supports.
- **Max (18-20%)**: best idea out of all ideas. Great narrative, great
  fundamentals, great outlook. A max-tier claim demands max-tier evidence
  and explicit regime support.

Undersizing is called out: a starter-sized position on a thesis argued as
exceptional, in a GREEN regime, is a tier mismatch and must be justified
or resized.

### Position structure

- Holdings goal: ~7 (hard cap 10 is policy-enforced atm)
- Minimum initial position: 5% of portfolio. No dust positions. If an idea
  does not deserve 5%, it deserves zero and a watchlist entry.

### Regime exposure targets

- GREEN: 80-100% invested. High-beta buys and adds allowed when evidence
  supports them.
- YELLOW: 40-70%. New buys need stronger evidence and smaller sizing;
  trims and delayed entries preferred.
- RED: 0-20%. Exposure increases only via the extraordinary-opportunity
  escalation.

### Extraordinary opportunities

Full normal sizing caps apply to extraordinary trades in all regimes: if
it truly cleared the 'extraordinary' bar, it deserves size. However, this should be rare in theory, so 'extraordinary opportunity' frequency will be tracked and the bar may be tweaked.

## How tuning works

1. Edit a dial above.
2. Log it in the changelog with date and one-line rationale.
3. Prompts and the sizing stage read this file; policy hard caps are NOT
   changed here (those changes go through `risk_policy.md` + code)

## Changelog

- 2026-07-15: v1 created by extracting appetite dials from mandate v1
  (hybrid risk-split decision). No numeric changes.
