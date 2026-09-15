# Strategy beliefs

This document should be read by the reasoning agent before every serious decision. Strategy beliefs
are the maintainer's written views on how markets and the AI ecosystem behave. They explain why the
framework favors certain trades. `mandate.md` defines the agent's identity and judgment doctrine,
while this file defines the beliefs a decision can be mapped to.

## How to use these

- Every serious decision should map to at least one belief. List the IDs in the record's
  `strategy_belief_ids`. Policy rejects any BUY or ADD that has no mapping.
- Cite only the beliefs the thesis actually depends on. A belief that is merely consistent with the
  trade is not support for it.
- A belief is a prior, not evidence. It never replaces `source_claims`, the counter-thesis, or the
  variant perception test in `mandate.md`.
- If a decision contradicts a belief, say so explicitly in the record rather than leaving the ID off.

## Beliefs

- **SB-001: Bull markets are reflexive:** In GREEN regimes, price momentum, narrative acceleration,
  institutional attention, and capital flows can reinforce each other.
- **SB-002: Direct AI infrastructure exposure is preferred:** Favor semiconductors, data centers,
  power, networking, cloud infrastructure, and bottleneck suppliers over vague "AI-enabled" exposure.
- **SB-003: Momentum needs backing:** Price strength should not be the entire thesis.
- **SB-004: Market reaction to news:** In a bullish regime, good news should be rewarded more than
  bad news is punished.
- **SB-005: X alpha as narrative:** X can detect velocity, disagreement, crowding, and early themes,
  but X sentiment shouldn't be the entire thesis, double check.
- **SB-006: Few positions with conviction over constant activity:** Once exposure is in range,
  default to monitoring unless thesis invalidation or extraordinary opportunity appears.
- **SB-007: Losses do not automatically invalidate a thesis:** Review losses against price action,
  source evidence, regime behavior, and thesis invalidation criteria.
- **SB-008: Wins do not automatically validate a thesis:** Review major winners for process quality.
- **SB-009: Alignment risk is an underpriced driver:** Concern over AI alignment and safety, and the
  geopolitics around it (frontier-lab slowdowns, regulation, US–China competition and negotiation),
  can move AI asset prices more than markets currently assume. Direction is not yet adopted: monitor
  heavily, and act only when a specific mechanism is substantiated. The operating guidance is in
  `mandate.md` under "Alignment and geopolitical risk".
