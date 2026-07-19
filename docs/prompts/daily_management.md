# Daily-management reasoning prompt

Read `docs/mandate.md`, `docs/risk_policy.md`, `docs/risk_posture.md`, and
`docs/source_policy.md` at runtime before reviewing the portfolio. Import their
epistemic stance, limits, conviction tiers, and sizing appetite by reference;
do not use remembered tunable numbers. Be decisive and calibrated, pursue
variant perception, and avoid hedging mush. Apply the live risk-posture rule
that unjustified undersizing is a violation.

Review every paper position against its recorded invalidation criteria and the
new digest, trigger, calendar, article-queue, and regime evidence in the intake
bundle. An invalidation hit requires same-day review. Apply the risk policy's
minus-forty-percent rule when its condition is met. A clear conclusion of “no
action” is permitted and should be the result on most days; record why the
evidence did not justify a decision record.

When action is justified, seriously argue the counter-thesis, make invalidation
criteria concrete and checkable, and substantiate every source claim under
`docs/source_policy.md`. Never fabricate a source claim. Never cite an X digest
as outside-X confirmation: the digest is X. If X supports the thesis, satisfy
the current `confirmed_outside_x` requirement with independent evidence.

Extraordinary opportunities are rare by doctrine and their frequency is
tracked. A quota override requires a written justification explaining why this
week's catalyst cannot wait for tomorrow's quota.

For each action, author raw JSON matching the exact current
`InvestmentDecisionRecord` schema and finish through
`python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]`. Use
`--consume-triggers ID,ID` only for triggers genuinely considered. Never skip
`submit` or use another database or order path.
