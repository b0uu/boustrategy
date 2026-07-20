# Launches a single headless X-pipeline digester (or weekly) session for
# Windows Task Scheduler. Scoped to the permission allowlist in
# ops\headless-digester-settings.json (see plan 019's ops note) -- this
# session never has a human to answer a permission prompt, so anything not
# on that allowlist fails closed instead of hanging.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("morning", "midday", "close", "weekly")]
    [string]$Slot
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$ClaudeExe = "C:\Users\Administrator\AppData\Roaming\npm\claude.cmd"
$SettingsFile = Join-Path $RepoRoot "ops\headless-digester-settings.json"
# Encodes model + rubric version so x_route_decisions predictors stay
# analyzable across upgrades (plan 019's maintenance note).
$PredictorName = "claude-fable5-rubric1"

$LogDir = Join-Path $RepoRoot "data\logs\digester"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "$Slot-$Timestamp.log"

$Runbook = if ($Slot -eq "weekly") { "docs/x_pipeline/WEEKLY.md" } else { "docs/x_pipeline/DIGESTER.md" }

$Prompt = @"
You are an unattended, non-interactive session launched by Windows Task Scheduler. No human will respond to prompts or approve actions this turn.

Follow $Runbook exactly for slot=$Slot. Use predictor/session name '$PredictorName' wherever the runbook calls for one (e.g. the route --predictor argument).

If the runbook's first step reports a calendar no-op, stop immediately -- that is a normal, expected outcome, not an error.

Do not ask the user any questions, do not wait for confirmation, and do not attempt anything outside the runbook's steps. Complete every applicable step or stop and clearly state what blocked you.
"@

Set-Location $RepoRoot
"=== $Timestamp slot=$Slot ===" | Out-File -FilePath $LogFile -Encoding utf8

& $ClaudeExe -p $Prompt --settings $SettingsFile 2>&1 | Tee-Object -FilePath $LogFile -Append
$ExitCode = $LASTEXITCODE
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8
exit $ExitCode
