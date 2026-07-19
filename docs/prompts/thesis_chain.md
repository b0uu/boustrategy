> **DRAFT — PENDING HUMAN CHECKPOINT 5 SIGN-OFF. No decision-generating
> session may load this prompt until the maintainer approves it and
> records the approval in plans/README.md.**

# Thesis-chain reasoning prompt

Before reasoning, read `docs/mandate.md`, `docs/risk_policy.md`,
`docs/risk_posture.md`, and `docs/source_policy.md` at runtime. Treat those
files as authoritative and current. Apply the mandate's decisive, calibrated,
variant-perception stance: reach a clear conclusion without turning uncertainty
into hedging mush. Apply the risk posture's conviction tiers, sizing appetite,
and rule that unjustified undersizing is a violation. Do not rely on limits or
thresholds remembered from an earlier session.

For every candidate, work through this chain:

1. State the investable claim and the variant perception precisely.
2. Substantiate it with source claims that comply with `docs/source_policy.md`.
   Never fabricate a claim or source. If X contributed to the thesis, satisfy
   the `confirmed_outside_x` discipline with genuinely independent evidence.
   An X digest is still X and cannot serve as outside-X confirmation.
3. Argue the strongest serious counter-thesis. Do not write a token objection.
4. Define mandatory invalidation criteria that are concrete and checkable.
5. Place the conclusion in the conviction tier defined by
   `docs/risk_posture.md`, then size consistently with that tier and the live
   portfolio context. If proposing an extraordinary opportunity, remember that
   the designation is rare by doctrine and its frequency is tracked. Any quota
   override needs a written explanation of why this week's catalyst cannot wait
   for tomorrow's quota.
6. Produce raw JSON matching the exact current `InvestmentDecisionRecord`
   schema. Do not invent fields or omit required fields.
7. Save that JSON to a file and finish by running
   `python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]`
   (and `--consume-triggers ID,ID` only for triggers genuinely considered).

There is no alternate persistence or order path. Never instruct the operator to
skip `submit`.
