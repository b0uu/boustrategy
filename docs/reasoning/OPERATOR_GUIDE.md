# Operating paper and live-trial reasoning sessions

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

Double-click `start-boustrategy.cmd` in the repository root. A small server window stays open and
the **Operate** page opens in your browser. Keep that window open while using the interface. Closing
it stops the local dashboard. The page is available only on this machine at
`http://127.0.0.1:8378/operate`.

On the Operate page:

1. Select the intended date and X slot, then click **Load**.
2. Click **Copy digester prompt** and paste it into a fresh Codex or Claude session in this
   repository. The dashboard doesn't run this step itself, so you see the proposed work before any
   X Post-read credits can be spent.
3. When the agent finishes the digest, reload the same date. Check that the digest file and database
   run are ready.
4. Click **Prepare paper session**. This refreshes prices and calendar data, settles eligible paper
   intents, evaluates triggers, publishes the regime, and builds the static intake. It doesn't read
   X or contact a broker.
5. Check the preparation receipt in the readiness panel. Then click **Copy reasoning prompt** and
   paste it into a new agent session. The button stays unavailable until preparation succeeds.
6. After reasoning finishes, use the **Decisions** and **Portfolio** pages to inspect records,
   policy outcomes, fills, cash, and positions. An intent normally fills only when a later session
   has the next market-open price bar.

The interface is deliberately supervised. It copies the two agent prompts instead of silently
starting model runs. The Operate page remains paper-only and can't send orders to a live brokerage.

## Private dashboard modes

The localhost dashboard is a private personal operator panel and test surface. It may show private
operational data and must remain bound to `127.0.0.1`.

- **Paper operator** keeps the existing paper preparation and reasoning workflow.
- **Live trial** shows one shared market and research intake with separate Codex and Claude profile
  cards. The agents receive the same research input but never share account snapshots, holdings,
  quotas, decisions, intents, packets, or broker lifecycle state.
- **Executions** remains the append-only broker ledger and execution-only handoff.

The dashboard copies exact prompts for manually started agent sessions. It doesn't launch agents,
schedule work, call Robinhood, or place an order. Scheduling is still deferred. The eventual
public dashboard is a separate public-safe product and isn't part of this private implementation.

## Live-trial boundary under development

The **Executions** page now exposes the broker-neutral live ledger and the prompt for a separate
execution-only agent. It isn't an order-entry form. Live order placement remains unavailable until
an account profile is explicitly bound and enabled in the gitignored `ops/live.local.json`, a
policy-approved live intent exists for that same profile, and a fresh broker preflight produces an
unexpired execution packet.

Codex and Claude use separate profile IDs, account aliases, account fingerprints, order intents,
packets, broker records, and lifecycle events. The example profiles use flexible funded capital
and a temporary $20 per-order brake. They record that the user has chosen no manual approval
between a successful broker review and exact placement, but they don't enable either profile or
contain a broker credential.

The detailed execution contract is in `docs/execution/EXECUTOR.md`. Don't paste its prompt into an
investment-reasoning session. The execution agent may verify and place one prepared packet, but it
may not choose a security, change a thesis, resize an order, or act on the other agent's account.

## If the launcher doesn't open

Open PowerShell in the repository root and run `python -m app.dashboard.server`, then visit
`http://127.0.0.1:8378/operate`. If Python reports a missing package, install the project's
development dependencies once with `python -m pip install -e ".[dev]"`.

`RUNBOOK.md` remains the agent-facing execution contract. You don't need to work through its
commands yourself during a normal session. The reasoning agent follows it after you paste the
prompt from the Operate page.

## What you should check as the human operator

- The latest digest completed and isn't stale.
- Outside-X confirmation is genuinely independent when X influenced a thesis.
- Source timestamps existed by the session date.
- The model didn't invent a source, ticker mapping, or market expectation.
- A no-action conclusion still explains what evidence would have changed it.
- Submission went through `app.reason.run submit`; no record or position was edited directly.
