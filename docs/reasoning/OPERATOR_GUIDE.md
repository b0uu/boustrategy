# Operating a paper reasoning session

`RUNBOOK.md` isn't an automated trading script. It is the contract for one fresh, supervised
reasoning session. The scheduled digester collects and ranks information. The reasoning session
starts separately, reviews that information alongside the portfolio and policy, and may produce a
paper order intent. It never reaches a live broker.

## What happens in one session

1. **Settle prior paper intents.** `app.paper.run settle` looks for approved order intents that
   haven't been filled. If the next daily opening-price bar is available, it records a simulated
   fill and updates paper cash and positions. If the price is missing, the intent remains safely
   awaiting data.
2. **Refresh prices and evaluate triggers.** The trigger command refreshes daily prices for the
   watchlist and current holdings, then records unusual price, volume, calendar, and digest events
   that deserve consideration. A trigger asks the model to look. It doesn't imply a trade.
3. **Publish the market regime.** The regime scorer refreshes SPY and QQQ history and records the
   deterministic GREEN, YELLOW, or RED state that policy will later enforce.
4. **Build a cold intake.** The intake command writes a static bundle containing the published
   regime, pending triggers, recent actionable digest items, article queue, calendar, and the
   $5,000 paper portfolio. "Cold" means the reasoning model starts from this recorded context
   instead of relying on memory from an earlier chat.
5. **Run the reasoning pass.** A fresh agent reads the bundle and the current mandate, policy,
   source rules, and prompts. It reviews existing positions and researches serious candidates.
   Most sessions may end with no action.
6. **Create records only for real conclusions.** An actionable conclusion is written as an exact
   `InvestmentDecisionRecord` JSON object. A no-action session doesn't create a fake HOLD or PASS
   record merely to produce output.
7. **Submit through the gate.** The submit command validates the JSON, applies deterministic
   policy, and creates a paper order intent only when both layers approve it. Direct database
   edits aren't an alternative.
8. **Write the session log.** The reasoning-session Markdown records what was considered,
   declined, submitted, or rejected. This is part of the evaluation dataset, especially when the
   correct result was no action.

## How to run the next session

From PowerShell in the repository root, choose the market date you want the session to represent:

```powershell
$RunDate = "2026-08-25"
python -m app.paper.run settle
python -m app.triggers.run evaluate --date $RunDate
python -m app.regime.run score --date $RunDate
python -m app.reason.run intake --date $RunDate --out "data/reason_runs/$RunDate"
```

Check that the final command prints the path to `bundle.md`. Open it and make sure its date,
portfolio, regime, triggers, and digest headlines look plausible before continuing.

Then start a **fresh Codex or Claude session in the repository** and give it this instruction:

```text
Follow docs/reasoning/RUNBOOK.md for 2026-08-25 using
data/reason_runs/2026-08-25/bundle.md. This is paper only. Complete the reasoning-session log even
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
