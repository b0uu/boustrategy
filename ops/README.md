# Scheduled operations

Public dashboard publication, serving, read-only smoke, and recovery are documented separately in
[`docs/public-release.md`](../docs/public-release.md). Those steps don't enable any task here.

## Current status: live operation on the Agentic account

As of September 9, 2026 the maintainer decided to skip the paper phase and operate live on the
dedicated Robinhood Agentic account with its small balance as the risk envelope. Every unattended
agent session runs through a dedicated Codex identity: a cheaper model for X digests and broker
reads, a stronger model for the investment review and for order execution. Task Scheduler is the
host trigger. The deterministic policy gate, the $20 per-order cap, the 60-second quote age and
the broker fingerprint checks are unchanged.

Nine tasks exist across two installers:

| Installer | Tasks | Trigger (ET, weekdays unless noted) | Worker |
| --- | --- | --- | --- |
| `install-digester-tasks.ps1` | `boustrategy-digester-morning`, `-midday`, `-close-halfday`, `-close`, `-weekly` | 08:45, 12:30, 14:45, 17:45, Sunday 18:00 | `run-digester-session.ps1`: headless Codex follows the X runbook, then `app.x.run verify` checks SQLite |
| `install-runtime-tasks.ps1` | `boustrategy-review-prepare`, `-prepare-halfday` | 18:10, 15:10 | `run-live-prepare.ps1`: deterministic market preparation, then a broker snapshot and the PREPARED live run through `app.broker.collector prepare-live` |
| `install-runtime-tasks.ps1` | `boustrategy-review-poller` | every minute 18:15 to 18:45 and 15:15 to 15:45 | `run-review-poller.ps1`: `app.reason.runtime scheduled --schedule live-close`; the worker refreshes the broker snapshot through the collector before authoring and again before submission |
| `install-runtime-tasks.ps1` | `boustrategy-live-execute` | 09:35 and 12:15 | `run-live-execution.ps1`: `app.broker.executor` runs one bounded Codex broker session per pending intent following `docs/execution/EXECUTOR.md`, then verifies the ledger |

The 14:45 and 15:xx triggers only do real work on NYSE half-days; every worker is calendar-aware
and no-ops otherwise. Both installers leave tasks disabled unless given `-Enable`, and
re-registering without that switch disables previously enabled definitions.

## One-time setup

### 1. The bot's Codex identity

Install the CLI so it is on PATH for scheduled tasks, then create a separate Codex home for the
account that will run unattended. Your personal `~/.codex` and VS Code Codex stay untouched.

```powershell
npm i -g @openai/codex
codex --version
$env:CODEX_HOME = "C:\Users\Administrator\.codex-boustrategy"
New-Item -ItemType Directory -Force $env:CODEX_HOME | Out-Null
Copy-Item .\ops\codex-home.example.toml "$env:CODEX_HOME\config.toml"
codex login
codex mcp login robinhood-trading
```

Log in with the bot's ChatGPT account. The Robinhood grant is stored per Codex home, so the
second login authorizes this identity against the Robinhood Agentic account. Run one interactive
`codex` session from the repository afterwards so the Windows sandbox finishes its first-run
setup with a human present. Then verify without spending much:

```powershell
"Reply with AUTH_OK only." | codex exec --sandbox read-only -m gpt-5.6-luna -
codex exec --sandbox read-only "Using only robinhood-trading tools, report account equity and buying power as JSON. Place no orders."
```

Never set `CODEX_HOME` as a user-wide variable; every wrapper sets it per process.

### 2. Local configuration

Copy `ops/digester.local.example.psd1` to `ops/digester.local.psd1` and fill in the Discord
webhook, the Codex home, and the two model IDs. The file is gitignored and read by every wrapper.
Treat the webhook URL as a password; if it leaks, delete the webhook in Discord and create a new
one. Notifications never include post content, prompts, credentials, or stack traces.

Test the webhook without printing the secret:

```powershell
$config = Import-PowerShellDataFile .\ops\digester.local.psd1
$body = @{ content = "BouStrategy Discord notification test" } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri $config.DiscordWebhookUrl -Method Post -ContentType "application/json" -Body $body
```

### 3. Host checks

```powershell
Get-Command python, codex
[bool][Environment]::GetEnvironmentVariable("X_BEARER_TOKEN", "User")
python -m app.x.run seed
python -m app.x.run status
```

The `python` on PATH must import the project with its dependencies, since the tasks don't
activate a virtual environment. Back up `data\boustrategy.db` before enabling anything.

### 4. Live schedule revision

The runtime only claims occurrences for an enabled `scheduled` revision. The live schedule is
`live-close`: mode `live`, `account_id` equal to the profile's broker fingerprint,
`execution_profile_id` `codex`. Write it to `ops/runtime.schedule.local.json` (gitignored) with
`enabled` true, `schedule_mode` `"scheduled"` and a current `configured_at`, then:

Keep `due_local` at `18:15:00` and `early_close_due_local` at `15:15:00` with the 1,800-second
grace. The runtime claims an occurrence only between the due time and the end of grace, and the
poller task ticks from 18:15 to 18:45 (15:15 to 15:45 on half-days), so the two windows must
coincide. An earlier due time would expire before the first tick.

```powershell
python -m app.reason.runtime --db data/boustrategy.db --live-profiles ops/live.local.json configure --in ops/runtime.schedule.local.json
python -m app.reason.runtime --db data/boustrategy.db preview --schedule live-close
```

Every later change is a new file with `revision` incremented by one. `pause` and `resume` exist
for short stops without a new revision.

## Register the tasks

Open PowerShell as Administrator from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install-digester-tasks.ps1 -Enable
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install-runtime-tasks.ps1 -Enable
Get-ScheduledTask -TaskName "boustrategy-*" | Select-Object TaskName, State
```

The installers register every task to run in the interactive Administrator session with highest
privileges. Codex's Windows sandbox runner can't start under a non-interactive password or batch
logon (it times out connecting its runner pipe, verified September 9, 2026), so **don't** switch
the tasks to "Run whether user is logged on or not". Keep the server session signed in: disconnect
RDP rather than signing out, and sign back in after a reboot. Don't switch the task account unless
that account also has the Codex home, the repository, Python, and `X_BEARER_TOKEN`.

Recommended order: enable the five digester tasks first and watch a clean weekday of
`data\logs\digester\`. Then enable the four `boustrategy-review-*` and `boustrategy-live-execute`
tasks together. The evening chain is: close digest 17:45, live preparation 18:10 (market data,
broker snapshot, PREPARED run), review claimed at 18:15 with a fresh snapshot before authoring and
again before submission. A policy-approved BUY becomes a LIVE intent that night and is placed at
09:35 the next session through the execution task; the 12:15 trigger retries anything still
pending. Intents older than 48 hours are never executed.

## What to watch

- `data\logs\digester\<slot>-<timestamp>.log`: session output, then the verify line.
- `data\logs\runtime\prepare-*.log`: the preparation receipt path or the reason it refused.
- `data\logs\runtime\poller-<schedule>-<date>.log`: one block per minute. `waiting` with
  `dependency_missing` means the digest or receipt isn't there yet; `skipped` after the grace
  window means the day was missed and won't be replayed.
- `data\runtime-logs\`: bounded Codex event logs per attempt.
- `data\logs\runtime\prepare-live-*.log` and `execute-*.log`: the live preparation and execution
  wrappers. `data\logs\broker\` holds each broker session's output and `executions.jsonl`, one
  line per executed intent with the session's report and any ledger problems.
- The private dashboard (`start-boustrategy.cmd`) for decisions, policy outcomes, and fills.
- The dashboard's **Operations** page (`http://127.0.0.1:8378/operations`): task states and
  last results, agent readiness (Codex login, Robinhood grant, X token, models), the review
  schedule with pause/resume, occurrences, attempts with named cancel/retry, and log tails.
  Enable, disable and run-now buttons call the same Task Scheduler commands as the installers.

Discord receives digester completions and failures, prepare results, and poller ticks that
claimed or refused an actual run. Calendar no-ops and idle ticks stay in the logs.

## Recovery

- A failed digester run can be rerun by starting its task manually; `cycle` resumes a failed
  run and refuses to duplicate a completed one.
- A failed attempt is retried explicitly with `python -m app.reason.runtime retry --run <id>`,
  never by the poller.
- `python -m app.reason.runtime reconcile` marks attempts whose lease expired without completion.
- Registering either installer without `-Enable` disables its tasks; `pause` stops new claims
  while an active attempt finishes.

The persisted runtime is documented in [`docs/reasoning/RUNTIME.md`](../docs/reasoning/RUNTIME.md).
The digester never launches investment reasoning; the poller never reads X or touches a broker.
