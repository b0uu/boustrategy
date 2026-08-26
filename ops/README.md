# Scheduled digester operations

## Current status: intentionally disabled

As of August 26, 2026, all five `boustrategy-digester-*` tasks are disabled. BouStrategy is in a
manual operating phase while ingestion, reasoning, paper execution, and evaluation are refined.
This prevents unattended API spending and makes each run easy to inspect.

The planned promotion order is:

1. Run and review the complete paper process manually.
2. Build a dashboard that exposes inputs, decisions, policy results, positions, costs, and errors.
3. Re-enable unattended ingestion and reasoning in paper mode.
4. Consider live execution only after unattended paper operation has produced enough evidence for
   a separate human activation decision.

The task definitions haven't been deleted. The instructions below are retained for the later
automation phase and shouldn't be run during manual development unless the operating decision is
explicitly changed.

The task installer creates or replaces five Windows Task Scheduler entries. Each entry launches
`run-digester-session.ps1`, which starts a restricted Claude session, follows the X pipeline
runbook, writes a local log, and verifies that the expected database run actually completed.

## Optional Discord notifications

1. Create a webhook in the Discord channel's **Edit Channel > Integrations > Webhooks** screen.
2. Copy `ops/digester.local.example.psd1` to `ops/digester.local.psd1`.
3. Replace `REPLACE_ME` with the webhook URL. Never put the real URL in the example file.
4. Test it from the repository root without printing the secret:

   ```powershell
   $config = Import-PowerShellDataFile .\ops\digester.local.psd1
   $body = @{ content = "BouStrategy Discord notification test" } | ConvertTo-Json -Compress
   Invoke-RestMethod -Uri $config.DiscordWebhookUrl -Method Post -ContentType "application/json" -Body $body
   ```

The local config is gitignored. Scheduled runs send a short message after a real completion or a
failure. Calendar no-ops don't notify. A detected X budget warning is included in the completion
message. Tweet content, prompts, credentials, and stack traces aren't sent to Discord.

Treat the webhook URL as a password. Anyone who has it can post into the channel. If it appears in
a commit, terminal transcript, screenshot, or public message, delete the webhook in Discord and
create a new one.

## Install or refresh the scheduled tasks

1. Finish editing the approved `- @handle` lines in `docs/x_manual/README.md`.
2. From the repository root, reconcile the edited roster into SQLite:

   ```powershell
   python -m app.x.run seed
   python -m app.x.run status
   ```

3. Open PowerShell as Administrator. Task registration usually needs elevation.
4. Move to the repository:

   ```powershell
   Set-Location C:\Users\Administrator\Documents\projects\boustrategy
   ```

5. Repair Claude authentication for this Windows account. The unattended task currently requires
   a long-lived Claude subscription token:

   ```powershell
   & C:\Users\Administrator\AppData\Roaming\npm\claude.cmd setup-token
   ```

   Follow the interactive login instructions. Keep the resulting credential in Claude's own
   credential store; don't paste it into this repository or the Discord config. Then verify
   non-interactive authentication:

   ```powershell
   "Reply with AUTH_OK only." |
       & C:\Users\Administrator\AppData\Roaming\npm\claude.cmd -p --tools ""
   ```

6. Confirm the scheduled account can find the required programs and user-level X token:

   ```powershell
   Get-Command python
   Test-Path C:\Users\Administrator\AppData\Roaming\npm\claude.cmd
   [bool][Environment]::GetEnvironmentVariable("X_BEARER_TOKEN", "User")
   ```

   The last command should print `True` and never prints the token itself.

7. Register the tasks:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\install-digester-tasks.ps1
   ```

   Re-running this is safe. It replaces tasks with the same names instead of adding duplicates.

8. Verify the task definitions:

   ```powershell
   Get-ScheduledTask -TaskName "boustrategy-digester-*" |
       Select-Object TaskName, State

   Get-ScheduledTask -TaskName "boustrategy-digester-*" |
       Get-ScheduledTaskInfo |
       Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime
   ```

9. Open **Task Scheduler > Task Scheduler Library** and inspect the five `boustrategy-digester-*`
   tasks. The script enables `StartWhenAvailable`, wake-to-run, battery operation, a 30-minute
   limit, and one instance at a time.

10. If the server may log out or reboot, open each task's **Properties > General**, choose **Run
   whether user is logged on or not**, and enter the Windows password when prompted. Don't switch
   to another account unless that account also has Claude authenticated, the repository and
   Python available, and `X_BEARER_TOKEN` configured. Don't select **Do not store password** because
   the task needs network access.

11. After the next run, inspect `data/logs/digester/` and confirm the log ends with both a verified
    database status and `exit code: 0`. A Discord success message is useful observability, but the
    database verification remains the source of truth.
