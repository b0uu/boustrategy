# Reasoning worker runbook

For a plain-language operator walkthrough, see
[`docs/reasoning/OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).

Human checkpoint 5 was cleared on 2026-07-19. Run one paper reasoning session
in this order; keep the launch supervised until consecutive sessions prove the
operational loop is reliable:

Before launching the fresh reasoning worker, the human operator confirms the separate digester
session completed, then runs
`python -m app.reason.run prepare [--date YYYY-MM-DD] --out <directory>`. Preparation refreshes
required prices and calendar data, settles eligible prior intents, evaluates triggers, publishes
the regime, builds the cold intake, and writes `<directory>/preparation.json`. It refuses to run
if the same-day digest or its completed database run is missing. The reasoning worker receives
the resulting directory and does not rerun preparation.

1. Read `<directory>/preparation.json`, `<directory>/bundle.md`,
   `docs/prompts/thesis_chain.md`, and `docs/prompts/daily_management.md`, including every
   runtime document they require.
2. Author zero or more decision-record JSON files. “No action” is a valid and
   expected result.
3. Submit each record separately:
   `python -m app.reason.run submit --in <file> [--date YYYY-MM-DD]`
   with `--consume-triggers ID,ID` only when appropriate.
4. Append what was considered, what was declined, and why to
   `data/reasoning_sessions/<date>.md`. The no-action record is evaluation gold.

never edit digests/labels/roster/maintainer docs; never write to the db except via `submit`; never continue into digester work (separate seam, separate session).

## Live dual-agent trial

Live mode begins only after the operator has saved a broker-sourced
`LivePortfolioSnapshot` for each enabled profile and prepared one shared bundle plus one
`ReasoningRun` per profile. Each fresh reasoning session receives its exact reasoning run ID,
execution profile ID, shared bundle path and SHA-256, and its own snapshot ID.

1. Read `shared_bundle.md`, only the snapshot named by your run, and every required runtime
   document listed in the bundle. The shared market and research input is identical for both
   profiles. Account state is intentionally isolated.
2. Never read, compare, or act on the other profile's snapshot, holdings, quotas, decisions,
   intents, packets, broker lifecycle, or account. The paper portfolio is out of scope and must be
   ignored in live mode.
3. Namespace every decision ID with `<reasoning_run_id>_` and submit every record through
   `python -m app.reason.run submit --execution-profile <profile> --reasoning-run <run-id>
   --in <file> [--date YYYY-MM-DD]`. Never write a live decision, intent, or link directly.
4. Complete the run through `python -m app.reason.run complete-live --in <run-file>`. Use one
   terminal result: `NO_ACTION`, `DECISIONS_AUTHORED`, or `FAILED`. Always include a concise public
   summary. No action still requires durable completion and a public summary.

The reasoning session stops after terminal completion. It doesn't build execution packets, call
Robinhood, review orders, or place trades.
