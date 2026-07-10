# Plan 004: Establish DX baseline — ruff, mypy, and a root AGENTS.md

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 01193d1..HEAD -- pyproject.toml AGENTS.md`
> The implementation baseline was committed as `01193d1` ("schema and policy
> added"). Compare the excerpt below against the live file; on a mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (can run before or after plans 001-003; running it first gives those plans lint/type gates)
- **Category**: dx
- **Planned at**: commit `d0fc4b2`, 2026-06-12

## Why this matters

The repo's only verification gate is pytest. There is no linter, no formatter
check, and no type checker, even though the codebase is fully type-annotated
pydantic code that mypy (with the pydantic plugin) can check almost for free.
This project's roadmap (`boustrategy_spec.md` §13) has agents writing
schema/policy/state-machine code on top of this foundation — cheap static
gates catch exactly the class of mistakes generated code makes.

Separately, the maintainer's coding conventions live in
`scratchpad/AGENTS.md`, but `scratchpad/` is listed in `.gitignore` — the
conventions are invisible to any agent or contributor working from a fresh
clone, and unversioned. A root `AGENTS.md` makes the conventions and the
build/test commands discoverable.

## Current state

- `pyproject.toml` — full current content:

```toml
[project]
name = "boustrategy"
version = "0.1.0"
description = "Investment decision harness for BouStrategy."
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- No `AGENTS.md` or `CLAUDE.md` exists at the repo root.
- `scratchpad/AGENTS.md` exists locally (gitignored). Its rules, inlined here
  so you do not depend on that file existing:
  1. Crash early — no protective try/except around inherently safe
     operations; try/except only at real failure boundaries (network, file
     I/O, untrusted input). Never swallow exceptions.
  2. No premature abstractions — no single-use helpers/wrappers; abstract
     only when logic repeats in 3+ separate places. Prefer explicit, inline,
     legible code.
  3. Comments — never "what"/"how" comments; only "why" comments for
     non-obvious business logic or edge cases. Prefer self-documenting names.
  4. Prefer modern language primitives over utility libraries.
- Layering rule (from `docs/decision_record.md`): the schema layer
  (`app/schemas/`) validates shape/types/enums/local consistency like a
  parser; the policy layer (`app/policy/`) decides whether a valid record is
  allowed under BouStrategy rules. Code must not blur these layers.
- Code layout: `app/schemas/`, `app/policy/`, tests mirror it under
  `tests/schemas/`, `tests/policy/`, shared fixtures in `tests/fixtures/`.

## Commands you will need

| Purpose   | Command                              | Expected on success |
|-----------|--------------------------------------|---------------------|
| Install   | `python -m pip install -e .[dev]`    | exit 0              |
| Tests     | `python -m pytest -q`                | all pass, exit 0    |
| Lint      | `python -m ruff check .`             | exit 0 (after step 2) |
| Format    | `python -m ruff format --check .`    | exit 0 (after step 2) |
| Typecheck | `python -m mypy app tests`           | exit 0 (after step 3) |

## Scope

**In scope** (the only files you should modify/create):

- `pyproject.toml`
- `AGENTS.md` (create, repo root)
- Mechanical fixes inside `app/` and `tests/` **only** where ruff or mypy
  report an error (import order, unused imports, missing annotations);
  behavior must not change.

**Out of scope** (do NOT touch):

- `scratchpad/` — gitignored maintainer workspace; do not move or delete it.
- `.gitignore` — leave `scratchpad/` ignored.
- `boustrategy_spec.md`, `docs/` — no doc rewrites in this plan.
- Any CI configuration — no remote/CI platform is configured; do not invent
  a workflow file.
- Any behavioral code change. If a lint/type error cannot be fixed without
  changing behavior, that's a STOP condition.

## Git workflow

- Branch: `advisor/004-dx-baseline`
- Commit style: short lowercase imperative summary, matching existing history.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add dev dependencies and tool config

In `pyproject.toml`, extend the dev extra and append tool sections:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
plugins = ["pydantic.mypy"]
strict = true
```

Then reinstall: `python -m pip install -e .[dev]`.

**Verify**: `python -m ruff --version` and `python -m mypy --version` both
exit 0.

### Step 2: Make lint and format pass

Run `python -m ruff check . --fix` then `python -m ruff format .`. Review
what changed: only mechanical fixes (import sorting, quoting, spacing) are
acceptable. The codebase is 6 small files; expect few or no findings.

**Verify**: `python -m ruff check .` → exit 0; `python -m ruff format --check .`
→ exit 0; `python -m pytest -q` → all pass.

### Step 3: Make mypy pass

Run `python -m mypy app tests`. Fix reported issues mechanically (e.g. adding
`-> None` to test functions, annotating `decision_record_with(**overrides:
object)` appropriately). If strict mode produces errors that require
behavioral changes or pervasive `# type: ignore` comments, relax per-module
strictness for `tests.*` only:

```toml
[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```

`app/` must pass full strict with zero `# type: ignore`.

**Verify**: `python -m mypy app tests` → exit 0, "no issues found";
`python -m pytest -q` → all pass.

### Step 4: Write the root AGENTS.md

Create `AGENTS.md` at the repo root with exactly these sections:

1. **Project** — two sentences: BouStrategy is an autonomous investment
   decision harness; LLM reasoning produces Investment Decision Records that
   must pass schema validation (`app/schemas/`) then deterministic policy
   checks (`app/policy/`) before any order can exist. Point to
   `boustrategy_spec.md` (vision) and `docs/decision_record.md` (current
   backbone).
2. **Commands** — the five commands from the table above, verbatim.
3. **Layout** — `app/schemas/` (shape validation, parser-like),
   `app/policy/` (rule evaluation on valid records), `tests/` mirrors `app/`,
   shared fixtures in `tests/fixtures/`.
4. **Conventions** — the four numbered rules inlined in "Current state"
   above, plus: schema/policy layering must not blur (schemas never embed
   policy decisions; policy never re-validates shape); policy rejection
   reasons are lowercase snake_case strings; tests are plain pytest functions
   in arrange/act/assert style.

**Verify**: `python - <<'EOF'` reading `AGENTS.md` confirms all four section
headers exist, or simply: `grep -c "^#" AGENTS.md` ≥ 4.

## Test plan

No new behavior, so no new unit tests. The gates themselves are the tests:

- `python -m pytest -q` → all pass (unchanged count from before this plan)
- `python -m ruff check .` → exit 0
- `python -m ruff format --check .` → exit 0
- `python -m mypy app tests` → exit 0

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pip install -e .[dev]` exits 0 and installs ruff + mypy
- [ ] `python -m ruff check .` exits 0
- [ ] `python -m ruff format --check .` exits 0
- [ ] `python -m mypy app tests` exits 0
- [ ] `python -m pytest -q` exits 0 with the same number of passing tests as before the plan
- [ ] `AGENTS.md` exists at repo root with Project / Commands / Layout / Conventions sections
- [ ] `git status --porcelain` shows changes only to `pyproject.toml`, `AGENTS.md`, and mechanically-fixed files under `app/` or `tests/`

## STOP conditions

Stop and report back (do not improvise) if:

- `pyproject.toml` content doesn't match the excerpt in "Current state".
- `ruff format` produces a diff that is not purely mechanical (anything
  beyond whitespace/quotes/import order/line wrapping).
- mypy strict on `app/` cannot pass without a behavioral change or a
  `# type: ignore` — report the specific error instead of suppressing it.
- An `AGENTS.md` or `CLAUDE.md` already exists at the repo root (it didn't at
  planning time; reconcile rather than overwrite).

## Maintenance notes

- When CI is eventually set up (no platform configured today), the four gate
  commands in AGENTS.md are the pipeline definition — keep them as the single
  source of truth.
- Plans 001-003, if executed after this one, must also pass
  ruff/mypy gates; their done criteria say pytest only, so the executor of
  those plans should additionally run the gates listed in root AGENTS.md once
  it exists.
- If the maintainer updates conventions in `scratchpad/AGENTS.md`, the root
  `AGENTS.md` is the published copy — keep them in sync manually or retire
  the scratchpad copy.
