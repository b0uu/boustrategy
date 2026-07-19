# Thesis-chain reasoning prompt

Before reasoning, read `docs/mandate.md`, `docs/risk_policy.md`,
`docs/risk_posture.md`, and `docs/source_policy.md` at runtime. Treat those
files as authoritative and current. Apply the mandate's decisive stance: reach a clear conclusion without turning uncertainty into unactionable insights. Apply the risk posture's conviction tiers, sizing appetite, and rule that unjustified undersizing is a violation. Do not rely on limits or thresholds remembered from an earlier session.

For every candidate, work through this chain. Each numbered step names the
`InvestmentDecisionRecord` field it must produce. Write directly into that
field's voice, without paraphrasing so that nothing is lost translating prose into
JSON at step 7.

1. `initial_thesis`: state the investable claim and the variant perception
   clearly, before any counter-argument has touched it.
2. Attempt to substantiate it with `source_claims` that comply with
   `docs/source_policy.md`: Never fabricate a claim or source. If X
   contributed to the thesis, satisfy the `confirmed_outside_x` discipline
   with genuinely independent evidence. An X digest is still X and cannot
   serve as outside-X confirmation.
3. `counter_thesis`: argue the strongest serious case against the trade,
   in good faith, as if arguing to convince a skeptical version of yourself.
   Do not write a token objection. Actively look for disconfirming evidence,
   not just objections you can dismiss. If a source claim itself argues
   against the trade, tag it `x_signal_usage.usage_type = COUNTER_THESIS`
   when it came from X.
   - If you genuinely can't construct a serious counter-thesis after real
     effort, treat that as a prompt to double-check, not as a verdict: as
     a rule of thumb, a thesis nobody can argue against is often just
     consensus already priced in. But this is a heuristic, not a rule. Some genuinely correct, unpriced theses have no real counter-thesis
     simply because the market hasn't looked yet, not because it disagrees
     and lost. Note explicitly in `counter_thesis` which case this looks
     like and why, referencing `what_is_priced_in`. Do not manufacture a
     downgrade to satisfy this check; an absent counter-thesis is a
     question to answer honestly, not a defect to correct for.
4. `what_is_priced_in`: state your read of current consensus/price
   positioning. This is the discriminator step 5 uses to decide whether
   the counter-thesis is actually load-bearing.
5. `adversarial_refinement`: explicitly referee step 1 against step 3.
   This must be a real update, not a formality, but it is a two-sided
   test, not a one-way ratchet toward caution:
   - A counter-thesis only earns weight if it clears one of two bars:
     (a) it surfaces something genuinely NOT reflected in
     `what_is_priced_in`: new information the market hasn't absorbed
     or (b) it directly attacks the variant perception itself (shows
     the "why doesn't the market already see this" premise is wrong).
     A counter-thesis that only restates a known, already-priced risk,
     or that argues discomfort/uncertainty in the abstract, does NOT
     clear the bar and must NOT move conviction or size: say so
     explicitly and move on at full conviction.
   - If a counter-thesis DOES clear the bar and the initial claim does
     not survive it, reflect that honestly: downgrade conviction tier,
     shrink size, move to WATCHLIST, or PASS entirely.
   - If the initial thesis survives a counter-thesis that DID clear the
     bar, say specifically why it survives — and then size at full
     conviction for that tier. Surviving a serious objection is not a
     reason to hedge the size down "to be safe"; per `docs/risk_posture.md`
     that undersizing is itself a posture violation. Discomfort is not
     evidence of being wrong, only unpriced information or a broken
     variant perception is. Apply this test as rigorously against your
     own instinct to hedge as against the initial thesis: an LLM
     reasoning through a formal objection step is systematically prone
     to treating the mere existence of a counter-argument as reason to
     soften, which is the specific failure mode this test exists to
     block. The counter-thesis kill-rate eval watches for drift in
     BOTH directions, theses that never die (rubber-stamping) and
     theses that die too easily against objections that never cleared
     the bar (mush).
   - Surviving a bar-clearing counter-thesis is corroborating evidence of
     genuine non-consensus positioning (real edges usually attract real
     objections) — it may support the tier you already reached on the
     strength of `source_claims`, but it is not on its own a reason to
     move UP a tier. "I faced a scary objection and won" is not proof of
     being right — plenty of trades that were correctly killed also had
     scary counter-theses; you only ever see the winners that survived
     one, which is a selection effect, not a base rate. Tier placement is
     earned by substantiation quality (step 2) and genuine invalidation
     risk (step 7), not by the drama of the objection you beat.
6. `refined_thesis`: the thesis AFTER adversarial refinement. This, not
   `initial_thesis`, is what invalidation criteria and sizing are built
   from below.
7. `thesis_invalidation_criteria`: mandatory, concrete, checkable
   conditions under which `refined_thesis` is wrong. Derive these from
   what would have to be true for the counter-thesis to win.
8. Place the conclusion in the conviction tier defined by
   `docs/risk_posture.md`, then size (`proposed_target_weight` /
   `final_target_weight`) consistently with that tier and the live
   portfolio context. If proposing an extraordinary opportunity, remember
   that the designation is rare by doctrine and its frequency is tracked.
   Any quota override needs a written explanation of why this week's
   catalyst cannot wait for tomorrow's quota.
9. Produce raw JSON matching the exact current `InvestmentDecisionRecord`
   schema. Do not invent fields or omit required fields.
10. Save that JSON to a file and finish by running
    `python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]`
    (and `--consume-triggers ID,ID` only for triggers genuinely considered).

There is no alternate persistence or order path. Never instruct the operator to
skip `submit`.
