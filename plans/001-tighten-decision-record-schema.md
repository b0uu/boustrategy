# Plan 001: Tighten InvestmentDecisionRecord schema validation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat d0fc4b2..HEAD -- app/schemas/ tests/`
> NOTE: at planning time (2026-06-12), `app/`, `tests/`, and `pyproject.toml`
> were **untracked** in git, so this diff may be empty even if files changed.
> The authoritative drift reference is the "Current state" excerpts below —
> compare them against the live code before proceeding; on a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `d0fc4b2`, 2026-06-12

## Why this matters

`InvestmentDecisionRecord` is the schema gate in this project's core safety
pipeline: model reasoning → decision record → **schema validation** → policy
evaluation → approval/rejection (see `docs/decision_record.md`). Three holes
were confirmed empirically:

1. A whitespace-only ticker (e.g. `"   "`) passes validation and becomes an
   **empty string**, because Pydantic enforces `min_length=1` on the raw input
   *before* the strip/uppercase field validator runs.
2. Naive (timezone-less) datetimes are accepted for `created_at` and
   `source_timestamp`, even though the spec's reliability rule requires every
   source to be timestamped for audit purposes — naive timestamps are ambiguous
   in an audit trail.
3. `SourceClaim.source_type` is a free-form string, but the project spec
   (`boustrategy_spec.md` §7, Source Pack object) defines a closed vocabulary:
   `SEC | COMPANY_IR | NEWS | X | PRICE_DATA | MACRO | ETF_ISSUER | INTERNAL_MEMO`.
   Free-form values defeat downstream source classification.

Additionally, `XSignalUsage` allows incoherent states: `used=False` combined
with `usage_type="IDEA_SOURCE"` or `confirmed_outside_x=True` validates today.

## Current state

Files:

- `app/schemas/decision_record.py` — the only schema module; contains all
  enums, `SourceClaim`, `XSignalUsage`, and `InvestmentDecisionRecord`.
- `tests/schemas/test_decision_record_schema.py` — schema tests (8 tests).
- `tests/fixtures/decision_records.py` — `valid_decision_record_data()`
  returns a fully valid BUY record dict; tests mutate copies of it.

The buggy ticker handling, `app/schemas/decision_record.py:74` and `:109-112`:

```python
    ticker: str = Field(min_length=1, max_length=12)
    ...
    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()
```

The naive-datetime fields, `app/schemas/decision_record.py:48` and `:72`:

```python
    source_timestamp: datetime      # in SourceClaim
    ...
    created_at: datetime            # in InvestmentDecisionRecord
```

Free-form source type, `app/schemas/decision_record.py:47`:

```python
    source_type: str = Field(min_length=1)
```

`XSignalUsage` validator, `app/schemas/decision_record.py:53-65`:

```python
class XSignalUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used: bool = False
    usage_type: XSignalUsageType = XSignalUsageType.IRRELEVANT
    summary: str = ""
    confirmed_outside_x: bool = False

    @model_validator(mode="after")
    def require_summary_when_used(self) -> "XSignalUsage":
        if self.used and not self.summary.strip():
            raise ValueError("x_signal_usage.summary is required when X is used")
        return self
```

Repo conventions (from the maintainer's agent guidance):

- Crash early; no defensive try/except around safe operations.
- No premature abstractions; explicit inline code over clever DRY.
- Comments only for non-obvious "why"; never "what"/"how" comments.
- Tests are plain pytest functions, arrange/act/assert with a blank line
  between phases — match the style of
  `tests/schemas/test_decision_record_schema.py:15-20`.

## Commands you will need

| Purpose | Command                        | Expected on success |
|---------|--------------------------------|---------------------|
| Install | `python -m pip install -e .[dev]` | exit 0           |
| Tests   | `python -m pytest -q`          | all pass, exit 0    |

(Verified during recon: 17 tests pass in ~0.2s at planning time.)

## Scope

**In scope** (the only files you should modify):

- `app/schemas/decision_record.py`
- `tests/schemas/test_decision_record_schema.py`
- `docs/decision_record.md` (the "Schema rules" section only)

**Out of scope** (do NOT touch, even though they look related):

- `app/policy/decision_policy.py` — policy-layer changes are plan 002.
- `tests/fixtures/decision_records.py` — the fixture is already valid under
  the new rules; if you find you must change it, that's a STOP condition.
- `boustrategy_spec.md` — the spec is the human-owned vision document.

## Git workflow

- Branch: `advisor/001-tighten-decision-record-schema`
- Commit style: short lowercase imperative summary, matching existing history
  (e.g. `added decision_record.md to detail backbone before further development`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Fix ticker normalization order and add format validation

In `app/schemas/decision_record.py`, replace the `normalize_ticker` validator
so emptiness and format are enforced *after* normalization. Add `import re`
at the top of the file. Target shape:

```python
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")


    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not TICKER_PATTERN.fullmatch(normalized):
            raise ValueError(
                "ticker must be 1-12 characters of A-Z, digits, '.' or '-', starting with a letter"
            )
        return normalized
```

The pattern intentionally allows class-share forms like `BRK.B` and `BF-B`.
Keep `Field(min_length=1, max_length=12)` on the field — it gives cheap early
rejection on raw input; the regex is the authoritative check.

**Verify**: `python -m pytest tests/schemas -q` → all pass (existing
`test_valid_buy_record_passes_validation` still asserts `ticker == "NVDA"`
from input `"nvda"`).

### Step 2: Require timezone-aware datetimes

In `app/schemas/decision_record.py`, import `AwareDatetime` from `pydantic`
and change:

- `SourceClaim.source_timestamp: datetime` → `source_timestamp: AwareDatetime`
- `InvestmentDecisionRecord.created_at: datetime` → `created_at: AwareDatetime`

Remove the now-unused `from datetime import datetime` import only if nothing
else in the file uses it.

**Verify**: `python -m pytest -q` → all pass (the fixture already uses
`tzinfo=UTC` datetimes).

### Step 3: Constrain source_type to the spec vocabulary

Add a `SourceType` enum next to the other enums in
`app/schemas/decision_record.py` and use it in `SourceClaim`:

```python
class SourceType(StrEnum):
    SEC = "SEC"
    COMPANY_IR = "COMPANY_IR"
    NEWS = "NEWS"
    X = "X"
    PRICE_DATA = "PRICE_DATA"
    MACRO = "MACRO"
    ETF_ISSUER = "ETF_ISSUER"
    INTERNAL_MEMO = "INTERNAL_MEMO"
```

Change `SourceClaim.source_type: str = Field(min_length=1)` to
`source_type: SourceType`.

**Verify**: `python -m pytest -q` → all pass (the fixture already uses
`"COMPANY_IR"`).

### Step 4: Enforce XSignalUsage coherence

Extend the existing `require_summary_when_used` validator in `XSignalUsage`
(keep the existing error message text exactly — a test matches on it):

```python
    @model_validator(mode="after")
    def require_summary_when_used(self) -> "XSignalUsage":
        if self.used:
            if not self.summary.strip():
                raise ValueError("x_signal_usage.summary is required when X is used")
            if self.usage_type == XSignalUsageType.IRRELEVANT:
                raise ValueError("x_signal_usage.usage_type cannot be IRRELEVANT when X is used")
        else:
            if self.usage_type != XSignalUsageType.IRRELEVANT:
                raise ValueError("x_signal_usage.usage_type must be IRRELEVANT when X is not used")
            if self.confirmed_outside_x:
                raise ValueError("x_signal_usage.confirmed_outside_x must be false when X is not used")
        return self
```

**Verify**: `python -m pytest -q` → all pass.

### Step 5: Add regression tests

Append to `tests/schemas/test_decision_record_schema.py`, following its
existing style (mutate `valid_decision_record_data()`, expect
`pytest.raises(ValidationError)`):

(listed in "Test plan" below)

**Verify**: `python -m pytest -q` → all pass, total test count ≥ 25.

### Step 6: Update the schema rules doc

In `docs/decision_record.md`, under `## Schema rules`, update/add bullets so
the documented rules match the code:

- ticker is normalized (trimmed, uppercased) and must match
  `A-Z`/digits/`.`/`-`, 1-12 chars, starting with a letter
- timestamps must be timezone-aware
- source claim `source_type` is limited to the source vocabulary
- X usage fields must be internally consistent (`used` ↔ `usage_type` ↔
  `confirmed_outside_x`)

**Verify**: `git diff --stat docs/decision_record.md` → only that file shows
doc changes.

## Test plan

New tests in `tests/schemas/test_decision_record_schema.py`, modeled after
`test_unknown_decision_fails_validation` (lines 15-20):

1. `test_whitespace_only_ticker_fails_validation` — `ticker = "   "` raises
   `ValidationError` (this is the confirmed bug; today it produces `ticker == ""`).
2. `test_ticker_with_invalid_characters_fails_validation` — `ticker = "NV DA"`
   raises.
3. `test_ticker_with_share_class_punctuation_passes` — `ticker = "brk.b"`
   validates to `"BRK.B"`.
4. `test_naive_created_at_fails_validation` — `created_at = datetime(2026, 6, 10, 12, 0)`
   (no tzinfo) raises.
5. `test_naive_source_timestamp_fails_validation` — same for
   `source_claims[0]["source_timestamp"]`.
6. `test_unknown_source_type_fails_validation` — `source_claims[0]["source_type"] = "BLOG"`
   raises.
7. `test_x_usage_used_with_irrelevant_type_fails_validation` —
   `{"used": True, "usage_type": "IRRELEVANT", "summary": "something", "confirmed_outside_x": False}`
   raises.
8. `test_x_usage_not_used_with_active_type_fails_validation` —
   `{"used": False, "usage_type": "IDEA_SOURCE", "summary": "", "confirmed_outside_x": False}`
   raises.
9. `test_x_usage_not_used_with_outside_confirmation_fails_validation` —
   `{"used": False, "usage_type": "IRRELEVANT", "summary": "", "confirmed_outside_x": True}`
   raises.

Verification: `python -m pytest -q` → all pass, 9 new tests included.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0; ≥ 26 tests collected (17 existing + 9 new)
- [ ] `python -c "from tests.fixtures.decision_records import valid_decision_record_data; from app.schemas.decision_record import InvestmentDecisionRecord; d = valid_decision_record_data(); d['ticker'] = '   '; InvestmentDecisionRecord.model_validate(d)"` exits non-zero with a `ValidationError`
- [ ] `git status --porcelain` shows changes only in the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `app/schemas/decision_record.py` does not exist in your working copy — the
  implementation was never committed to git (it was untracked at planning
  time) and your worktree predates it.
- The code at the cited locations doesn't match the "Current state" excerpts.
- Making the fixture in `tests/fixtures/decision_records.py` pass requires
  changing it — the fixture was verified valid under all new rules at
  planning time; needing to touch it means an assumption is wrong.
- Any existing test fails after your change for a reason you cannot trace to
  one of steps 1-4.

## Maintenance notes

- Plan 002 (policy gate fixes) builds test fixtures with X usage dicts; those
  fixtures were written to satisfy this plan's coherence rules, so landing
  this plan first is the recommended order, though there is no hard dependency.
- The ticker regex is US-listing-shaped (letters first, `.`/`-` share-class
  punctuation). If non-US listings ever enter scope, this regex is the place
  that will reject them — revisit deliberately, not as a hotfix.
- When the Source Pack schema is built (spec §7), reuse the `SourceType` enum
  introduced here rather than re-declaring the vocabulary.
