# Project

BouStrategy is an autonomous investment decision harness where LLM reasoning produces Investment Decision Records that must pass schema validation (`app/schemas/`) and then deterministic policy checks (`app/policy/`) before any order can exist. See `boustrategy_spec.md` for the vision, `docs/decision_record.md` for the record backbone, and `docs/mandate.md`, `docs/risk_policy.md`, and `docs/source_policy.md` for the maintainer-owned source of truth; code, schemas, and prompts must stay consistent with these strategy documents, and agents must not edit them without explicit instruction.

# Commands

- `python -m pip install -e .[dev]`
- `python -m pytest -q`
- `python -m ruff check .`
- `python -m ruff format --check .`
- `python -m mypy app tests`

# Layout

- `app/schemas/` validates shape, types, enums, and local consistency like a parser.
- `app/policy/` evaluates deterministic rules on valid records.
- `tests/` mirrors `app/`, with shared fixtures in `tests/fixtures/`.

# Conventions

1. Crash early. Do not add protective `try`/`except` around inherently safe operations; catch exceptions only at real failure boundaries such as network access, file I/O, and untrusted input, and never swallow exceptions.
2. Avoid premature abstractions. Do not create single-use helpers or wrappers; abstract only when logic repeats in at least three separate places, and prefer explicit, inline, legible code.
3. Write comments only to explain non-obvious business logic or edge cases, never to narrate what the code does or how it does it. Prefer self-documenting names.
4. Prefer modern language primitives over utility libraries.
5. Keep schema and policy layering separate: schemas never embed policy decisions, and policy never re-validates shape.
6. Write policy rejection reasons as lowercase snake_case strings.
7. Write plain pytest functions in arrange/act/assert style.
