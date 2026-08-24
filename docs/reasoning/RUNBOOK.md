# Reasoning worker runbook

For a plain-language operator walkthrough, see
[`docs/reasoning/OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).

Human checkpoint 5 was cleared on 2026-07-19. Run one paper reasoning session
in this order; keep the launch supervised until consecutive sessions prove the
operational loop is reliable:

1. Settle yesterday's paper intents: `python -m app.paper.run settle`.
2. Refresh prices and evaluate triggers:
   `python -m app.triggers.run evaluate [--date YYYY-MM-DD]`.
3. Publish the regime snapshot:
   `python -m app.regime.run score [--date YYYY-MM-DD]`.
4. Build a cold intake directory:
   `python -m app.reason.run intake [--date YYYY-MM-DD] --out <directory>`.
5. Read `<directory>/bundle.md`, `docs/prompts/thesis_chain.md`, and
   `docs/prompts/daily_management.md`, including every runtime document they
   require.
6. Author zero or more decision-record JSON files. “No action” is a valid and
   expected result.
7. Submit each record separately:
   `python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]`
   with `--consume-triggers ID,ID` only when appropriate.
8. Append what was considered, what was declined, and why to
   `data/reasoning_sessions/<date>.md`. The no-action record is evaluation gold.

never edit digests/labels/roster/maintainer docs; never write to the db except via `submit`; never continue into digester work (separate seam, separate session).
