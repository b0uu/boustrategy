# PROPOSAL — Risk posture v1

> **STATUS: DRAFT PROPOSAL, NOT IN EFFECT.** Drafted by Claude 2026-07-15
> as the tunable half of the maintainer's hybrid risk-split decision. The
> numbers below are lifted verbatim from the current mandate/decisions —
> nothing changes in effect when adopted; what changes is WHERE the dials
> live and that turning them no longer requires rewriting doctrine.
> Maintainer: edit, then move to `docs/risk_posture.md`.

---

# Risk posture

This document is the **tunable appetite layer**. It is consumed by the
sizing stage of decision workflows and by prompts; it never overrides
`risk_policy.md` (deterministic hard caps always bind above anything
here). The mandate governs how the agent *thinks*; this governs how much
it *bets* on what it concludes. The maintainer may retune any dial at any
time by editing this file and logging the change below.

## Current profile: AGGRESSIVE (v1, 2026-07-15)

### The core dial: EV over comfort

When calibrated analysis favors the uncomfortable option, take it at the
size conviction warrants. Safe-but-lower-EV sizing (timid weights on
high-conviction theses, idling in cash despite qualifying opportunities)
is a posture violation of the same severity as recklessness. Severe
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

- Holdings goal: ~7 (hard cap 10 is policy-enforced, not tunable here).
- Minimum initial position: 5% of portfolio. No dust positions. If an idea
  does not deserve 5%, it deserves zero and a watchlist entry.

### Regime exposure targets

- GREEN: 80-100% invested. High-beta buys and adds allowed when evidence
  supports them.
- YELLOW: 40-70%. New buys need stronger evidence and smaller sizing;
  trims and delayed entries preferred.
- RED: 0-20%. Exposure increases only via the extraordinary-opportunity
  escalation.

### Extraordinary-opportunity appetite

Full normal sizing caps apply to extraordinary trades in all regimes: if
it truly cleared the bar, it deserves real size. Expected to be rare;
clearance frequency and outcome quality are tracked metrics, and this
dial widens or tightens based on them.

## How tuning works

1. Edit a dial above.
2. Log it in the changelog with date and one-line rationale.
3. Prompts and the sizing stage read this file; policy hard caps are NOT
   changed here (those changes go through `risk_policy.md` + code).

## Changelog

- 2026-07-15: v1 created by extracting appetite dials from mandate v1
  (hybrid risk-split decision). No numeric changes.
