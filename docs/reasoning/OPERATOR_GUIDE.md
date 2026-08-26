# Operating a paper reasoning session

`RUNBOOK.md` isn't an automated trading script. It is the contract for one fresh, supervised
reasoning session. During the current manual phase, the operator starts ingestion and reasoning
deliberately, reviews each boundary, and may produce a paper order intent. The Windows digester
tasks are intentionally disabled. No part of this process reaches a live broker.

## What happens in one session

1. **Verify the information seam.** Preparation requires a rendered same-day digest backed by at
   least one completed SQLite digester run. A missing or unfinished run stops before price or
   portfolio state changes.
2. **Refresh prices and settle prior paper intents.** Preparation refreshes daily prices for the
   watchlist, current holdings, and unfilled intent tickers. It then fills eligible intents only
   through the selected session date. An intent without an eligible opening-price bar remains
   safely awaiting data.
3. **Evaluate triggers.** The preparation command records unusual price, volume, calendar, and
   digest events that deserve consideration. A trigger asks the model to look. It doesn't imply a
   trade.
4. **Publish the market regime.** The regime scorer refreshes SPY and QQQ history and records the
   deterministic GREEN, YELLOW, or RED state that policy will later enforce.
5. **Build a cold intake.** The preparation command writes a static bundle containing the published
   regime, pending triggers, recent actionable digest items, article queue, calendar, and the
   $5,000 paper portfolio. "Cold" means the reasoning model starts from this recorded context
   instead of relying on memory from an earlier chat.
6. **Run the reasoning pass.** A fresh agent reads the bundle and the current mandate, policy,
   source rules, and prompts. It reviews existing positions and researches serious candidates.
   Most sessions may end with no action.
7. **Create records only for real conclusions.** An actionable conclusion is written as an exact
   `InvestmentDecisionRecord` JSON object. A no-action session doesn't create a fake HOLD or PASS
   record merely to produce output.
8. **Submit through the gate.** The submit command validates the JSON, applies deterministic
   policy, and creates a paper order intent only when both layers approve it. Direct database
   edits aren't an alternative.
9. **Write the session log.** The reasoning-session Markdown records what was considered,
   declined, submitted, or rejected. This is part of the evaluation dataset, especially when the
   correct result was no action.

## How to run the next session

First run a fresh, supervised digester session for the intended date and slot. Give that session:

```text
Follow docs/x_pipeline/DIGESTER.md for 2026-08-26 using the close slot. This is a supervised
manual run. Stop after the digest is rendered and verified. Don't continue into investment
reasoning.
```

Change the date and slot as needed. This session may spend X Post-read credits within the hard
budget guard, so inspect its fetch and routing summary before starting another slot.

After the digester completes, return to PowerShell in the repository root and prepare the paper
reasoning session:

```powershell
$RunDate = "2026-08-26"
python -m app.reason.run prepare --date $RunDate --out "data/reason_runs/$RunDate"
```

The preparation command refuses to run unless SQLite records a completed same-day digester run
and the rendered digest exists. It refreshes required prices, settles eligible prior intents only
through `$RunDate`, evaluates triggers, publishes the regime, and builds the intake. Open both
`preparation.json` and `bundle.md`. Check the date, completed digester runs, price refreshes, fills,
awaiting intents, portfolio, regime, triggers, and digest headlines before continuing.

Then start a **fresh Codex or Claude session in the repository** and give it this instruction:

```text
Follow docs/reasoning/RUNBOOK.md for 2026-08-26 using
data/reason_runs/2026-08-26/bundle.md and its preparation.json receipt. This is paper only.
Complete the reasoning-session log even
if the correct result is no action. Show me every decision record and submission result.
```

Supervision at this stage means watching what the agent reads and checking its claimed sources,
not manually approving a trade around the policy engine. If it authors a decision JSON, it should
save it under the gitignored `data/reason_runs/<date>/` directory and submit it with the runbook's
command. The resulting status will say whether schema and policy accepted it and whether an order
intent was created.

After the session, inspect:

```powershell
Get-Content "data/reasoning_sessions/$RunDate.md"
python -m app.paper.run positions
python -m app.paper.run equity
```

An order intent normally fills only when a later session has the next market-open bar. No command
in this procedure can send an order to a live brokerage.

## What you should check as the human operator

- The latest digest completed and isn't stale.
- Outside-X confirmation is genuinely independent when X influenced a thesis.
- Source timestamps existed by the session date.
- The model didn't invent a source, ticker mapping, or market expectation.
- A no-action conclusion still explains what evidence would have changed it.
- Submission went through `app.reason.run submit`; no record or position was edited directly.
