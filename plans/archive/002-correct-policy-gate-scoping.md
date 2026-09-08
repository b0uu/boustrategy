# Plan 002: Correct policy gate scoping (escalation gate for RED/derisking; over-broad weight and X rules)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 01193d1..HEAD -- app/policy/ tests/policy/ docs/decision_record.md`
> The implementation baseline was committed as `01193d1` ("schema and policy
> added"). Compare the "Current state" excerpts below against the live code
> before proceeding; on a mismatch, STOP. This plan **requires plan 001 to
> have landed first** (it reads schema fields plan 001 introduces).

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (changes risk-gate semantics and reason-code strings; the semantics below were explicitly decided by the maintainer on 2026-07-08)
- **Depends on**: plans/001-tighten-decision-record-schema.md (hard — uses `extraordinary_opportunity` and `extraordinary_justification` fields added there)
- **Category**: bug
- **Planned at**: commit `d0fc4b2`, 2026-06-12; revised 2026-07-08 after maintainer decisions (baseline now `01193d1`)

## Why this matters

The policy engine is the deterministic risk gate between LLM reasoning and
broker orders ("No direct LLM-to-order path", `boustrategy_spec.md` §2).
Three scoping defects were confirmed empirically, and the maintainer has
decided the intended semantics for each:

1. **ADD escapes both risk gates, and the fix is an escalation gate, not a
   ban.** Today only BUY is blocked in a RED regime / DE_RISKING mode; ADD
   (which puts new money at risk exactly like BUY) is approved — confirmed:
   an ADD in RED + DE_RISKING passes. The maintainer's framework celebrates
   bold, evidence-backed action (spec SB-007), so the decided design is:
   BUY/ADD in RED or DE_RISKING is rejected **unless** the record explicitly
   declares `extraordinary_opportunity = true` with a written justification
   (schema fields from plan 001). Boldness stays possible; it just becomes
   declared and auditable instead of silent.
2. **Weight caps reject passive decisions.** A `HOLD` on an equity position
   that appreciated to 25% weight is rejected today (confirmed), as is a
   TRIM whose destination weight is still above the cap. The caps exist to
   limit what the agent *buys into* (spec §12 "Initial limits" are sizing
   limits). Decided: caps apply to exposure-increasing decisions (BUY, ADD)
   only.
3. **The X-confirmation rule over-applies.** The documented rule is "reject
   X-only **thesis** when `confirmed_outside_x` is false"
   (`docs/decision_record.md:78`). The implementation rejects *any* record
   where X was used without outside confirmation — including non-actionable
   decisions (a `PASS` was confirmed rejected) and records where X argued
   *against* the thesis (`COUNTER_THESIS` / `CROWDING_WARNING`). Decided:
   the rule applies only to actionable decisions where X supported the
   thesis (`IDEA_SOURCE` or `CONFIRMATION`).

## Current state

Files:

- `app/policy/decision_policy.py` — the whole policy engine (~56 lines):
  `PolicyResult`, `evaluate_decision_policy`, `_is_actionable`.
- `tests/policy/test_decision_policy.py` — 9 policy tests.
- `tests/fixtures/decision_records.py` — `valid_decision_record()` (a valid
  GREEN/CAPITAL_DEPLOYMENT equity BUY at weight 0.12) and
  `decision_record_with(**overrides)`. After plan 001 the fixture also has
  `primary_theme_id: "ai_semiconductors"`.
- `docs/decision_record.md` — "Policy rules" section lists the intended rules.

The gates as they exist today, `app/policy/decision_policy.py:19-44`:

```python
    if record.decision == Decision.BUY and record.regime_state == RegimeState.RED:
        reasons.append("buy_disallowed_in_red_regime")

    if record.decision == Decision.BUY and record.operating_mode == OperatingMode.DE_RISKING:
        reasons.append("buy_disallowed_in_derisking_mode")

    if (
        record.asset_type == AssetType.EQUITY
        and record.final_target_weight > MAX_EQUITY_TARGET_WEIGHT
    ):
        reasons.append("equity_target_weight_exceeds_limit")

    if record.asset_type == AssetType.ETF and record.final_target_weight > MAX_ETF_TARGET_WEIGHT:
        reasons.append("etf_target_weight_exceeds_limit")

    if record.decision in {Decision.BUY, Decision.ADD} and not record.strategy_belief_ids:
        reasons.append("missing_strategy_belief_mapping")

    if _is_actionable(record) and not record.thesis_invalidation_criteria:
        reasons.append("missing_invalidation_criteria")

    if _is_actionable(record) and not record.source_claims:
        reasons.append("missing_source_claims")

    if record.x_signal_usage.used and not record.x_signal_usage.confirmed_outside_x:
        reasons.append("x_signal_not_confirmed_outside_x")
```

`_is_actionable`, `app/policy/decision_policy.py:49-55`:

```python
def _is_actionable(record: InvestmentDecisionRecord) -> bool:
    return record.decision in {
        Decision.BUY,
        Decision.ADD,
        Decision.TRIM,
        Decision.SELL,
    }
```

After plan 001, `InvestmentDecisionRecord` has these fields (verify they
exist before starting — if absent, plan 001 has not landed: STOP):

```python
    extraordinary_opportunity: bool = False
    extraordinary_justification: str = ""
    primary_theme_id: str | None = None
```

Confirmed behavior at planning time (these are the bugs):

- `decision="ADD", regime_state="RED", operating_mode="DE_RISKING"` → approved.
- `decision="HOLD", final_target_weight=0.25` (equity) → rejected.
- `decision="PASS"` with X used as `COUNTER_THESIS`, unconfirmed → rejected.

Repo conventions: crash early, no premature abstractions, no "what" comments;
policy reasons are lowercase snake_case strings; tests are plain pytest
functions in arrange/act/assert style — match
`tests/policy/test_decision_policy.py:14-21`.

## Commands you will need

| Purpose | Command                           | Expected on success |
|---------|-----------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0              |
| Tests   | `python -m pytest -q`             | all pass, exit 0    |

## Scope

**In scope** (the only files you should modify):

- `app/policy/decision_policy.py`
- `tests/policy/test_decision_policy.py`
- `docs/decision_record.md` (the "Policy rules" section only)

**Out of scope** (do NOT touch, even though they look related):

- `app/schemas/decision_record.py` — schema-layer changes belong to plan 001.
- `tests/fixtures/decision_records.py` — overrides via `decision_record_with`
  are sufficient for every new test.
- `PolicyResult.adjusted_final_target_weight` — currently dead, handled in
  plan 003; leave it exactly as is.

## Git workflow

- Branch: `advisor/002-correct-policy-gate-scoping`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Replace the BUY-only blocks with BUY/ADD escalation gates

In `evaluate_decision_policy`, replace the two regime/mode gates. Define the
exposure-increasing set once at module level:

```python
_EXPOSURE_INCREASING = {Decision.BUY, Decision.ADD}
```

New gates (reason codes change because the semantics changed):

```python
    if (
        record.decision in _EXPOSURE_INCREASING
        and record.regime_state == RegimeState.RED
        and not record.extraordinary_opportunity
    ):
        reasons.append("buy_or_add_in_red_requires_extraordinary_opportunity")

    if (
        record.decision in _EXPOSURE_INCREASING
        and record.operating_mode == OperatingMode.DE_RISKING
        and not record.extraordinary_opportunity
    ):
        reasons.append("buy_or_add_in_derisking_requires_extraordinary_opportunity")
```

Note: the schema (plan 001) already guarantees that
`extraordinary_opportunity = true` carries a non-empty justification, so
policy does not re-check the justification text — layering stays clean.

Update the two existing tests that assert the old reason strings
(`test_rejects_buy_in_red_regime`, `test_rejects_buy_in_derisking_mode`) to
the new strings.

**Verify**: `python -m pytest tests/policy -q` → all pass.

### Step 2: Scope weight caps to exposure-increasing decisions

Change both weight-cap gates to require `record.decision in
_EXPOSURE_INCREASING` in addition to the existing asset-type and weight
conditions. The two existing weight-cap tests use the fixture default
decision `BUY`, so they keep passing unchanged.

**Verify**: `python -m pytest tests/policy -q` → all pass.

### Step 3: Scope the X-confirmation rule to thesis-supporting use on actionable decisions

Replace the X gate with:

```python
    thesis_supporting_x = record.x_signal_usage.usage_type in {
        XSignalUsageType.IDEA_SOURCE,
        XSignalUsageType.CONFIRMATION,
    }
    if (
        _is_actionable(record)
        and record.x_signal_usage.used
        and thesis_supporting_x
        and not record.x_signal_usage.confirmed_outside_x
    ):
        reasons.append("x_signal_not_confirmed_outside_x")
```

Add `XSignalUsageType` to the imports from `app.schemas.decision_record`.

**Verify**: `python -m pytest tests/policy -q` → all pass (the existing
`test_rejects_x_used_without_outside_confirmation` uses a BUY with
`IDEA_SOURCE`, which is still rejected).

### Step 4: Add regression tests

Append the tests listed in "Test plan" to
`tests/policy/test_decision_policy.py`.

**Verify**: `python -m pytest -q` → all pass.

### Step 5: Update the policy rules doc

In `docs/decision_record.md`, under `## Policy rules`, update the affected
bullets to match the new semantics:

- "reject BUY in RED." → "reject BUY or ADD in RED unless the record declares
  an extraordinary opportunity with justification."
- "reject new high beta BUY in DE_RISKING mode." → "reject BUY or ADD in
  DE_RISKING mode unless the record declares an extraordinary opportunity
  with justification."
- "reject stock target weight above 20%." → "reject BUY or ADD with stock
  target weight above 20%."
- "reject ETF target weight above 50%." → "reject BUY or ADD with ETF target
  weight above 50%."
- "reject X-only thesis when `confirmed_outside_x` is false." → "reject
  actionable decisions whose thesis used X (idea source or confirmation)
  without outside-X confirmation."

**Verify**: `git diff docs/decision_record.md` shows only those bullets changed.

## Test plan

New tests in `tests/policy/test_decision_policy.py`, modeled after
`test_rejects_buy_in_red_regime` (lines 14-21), using `decision_record_with`:

1. `test_rejects_add_in_red_regime_without_escalation` — `decision="ADD",
   regime_state="RED"` → not approved,
   `"buy_or_add_in_red_requires_extraordinary_opportunity"` in reasons.
2. `test_rejects_add_in_derisking_mode_without_escalation` — `decision="ADD",
   operating_mode="DE_RISKING"` → not approved,
   `"buy_or_add_in_derisking_requires_extraordinary_opportunity"` in reasons.
3. `test_allows_extraordinary_buy_in_red_regime` — `regime_state="RED",
   extraordinary_opportunity=True, extraordinary_justification="Panic selloff
   has disconnected price from intact AI capex evidence."` → approved.
4. `test_allows_extraordinary_add_in_derisking_mode` — `decision="ADD",
   operating_mode="DE_RISKING"` plus the same two escalation overrides →
   approved.
5. `test_allows_hold_above_equity_weight_cap` — `decision="HOLD",
   proposed_target_weight=0.25, final_target_weight=0.25` → approved
   (regression for the confirmed HOLD-rejection bug).
6. `test_allows_buy_at_exact_equity_weight_cap` —
   `proposed_target_weight=0.20, final_target_weight=0.20` → approved
   (boundary: exactly 0.20 is allowed).
7. `test_allows_counter_thesis_x_usage_without_outside_confirmation` —
   `decision="TRIM"` with
   `x_signal_usage={"used": True, "usage_type": "COUNTER_THESIS", "summary":
   "skeptics flagged crowding", "confirmed_outside_x": False}` → approved.
8. `test_allows_unconfirmed_x_on_non_actionable_decision` —
   `decision="PASS"` with
   `x_signal_usage={"used": True, "usage_type": "IDEA_SOURCE", "summary":
   "narrative velocity spike", "confirmed_outside_x": False}` → approved
   (regression for the confirmed PASS-rejection bug).
9. `test_rejects_buy_with_unconfirmed_x_confirmation_usage` — fixture BUY with
   `x_signal_usage={"used": True, "usage_type": "CONFIRMATION", "summary":
   "X confirmed the demand narrative", "confirmed_outside_x": False}` →
   not approved, `"x_signal_not_confirmed_outside_x"` in reasons.

Verification: `python -m pytest -q` → all pass, 9 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; ≥ 9 new tests in `tests/policy/test_decision_policy.py`
- [ ] `grep -rn "buy_disallowed_in_red_regime\|buy_disallowed_in_derisking_mode" app/ tests/` returns no matches (old reason codes fully renamed)
- [ ] `python -c "from tests.fixtures.decision_records import decision_record_with; from app.policy.decision_policy import evaluate_decision_policy; r = evaluate_decision_policy(decision_record_with(decision='ADD', regime_state='RED')); assert not r.approved"` exits 0
- [ ] `python -c "from tests.fixtures.decision_records import decision_record_with; from app.policy.decision_policy import evaluate_decision_policy; r = evaluate_decision_policy(decision_record_with(regime_state='RED', extraordinary_opportunity=True, extraordinary_justification='Evidence-backed dislocation.')); assert r.approved"` exits 0
- [ ] `python -c "from tests.fixtures.decision_records import decision_record_with; from app.policy.decision_policy import evaluate_decision_policy; r = evaluate_decision_policy(decision_record_with(decision='HOLD', proposed_target_weight=0.25, final_target_weight=0.25)); assert r.approved"` exits 0
- [ ] `git status --porcelain` shows changes only in the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `InvestmentDecisionRecord` has no `extraordinary_opportunity` field — plan
  001 has not landed; this plan depends on it.
- The gates in "Current state" don't match the live code.
- Any of this plan's X-usage test dicts fail *schema* validation — they were
  written to satisfy plan 001's coherence rules, so a schema rejection means
  one of the plans drifted.
- Any existing test fails for a reason you cannot trace to steps 1-3.

## Maintenance notes

- **Decided 2026-07-08 by the maintainer** (supersedes the earlier hard-block
  design): RED/DE_RISKING gates are escalation gates, not bans. The escape
  valve is `extraordinary_opportunity` + justification, mirroring the spec's
  §9 extraordinary-opportunity classification. If audit records later show
  the agent spamming the flag to bypass the gate, the countermeasures live in
  evals and prompt design first, and only then in tightening policy (e.g.
  requiring a matching trigger classification).
- After this plan, TRIM/SELL/HOLD records are never weight-capped. Exposure
  drift handling should come from the daily portfolio management chain, not
  from rejecting HOLDs.
- The X rule now ignores `COUNTER_THESIS`/`CROWDING_WARNING` usage. If a
  future eval shows the agent laundering thesis support through the
  counter-thesis field, tighten here.
