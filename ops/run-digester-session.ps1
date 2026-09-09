# Launches a single headless X-pipeline digester (or weekly) session for
# Windows Task Scheduler through the bot's own Codex identity. The session
# never has a human to answer a prompt, so it runs with approvals disabled
# inside Codex's workspace-write sandbox (network on, Robinhood MCP off) and
# is judged only by the deterministic `verify` check afterwards.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("morning", "midday", "close", "weekly")]
    [string]$Slot
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"

$LogDir = Join-Path $RepoRoot "data\logs\digester"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "$Slot-$Timestamp.log"
$LastMessageFile = Join-Path $LogDir "$Slot-$Timestamp.last-message.txt"

$DiscordWebhookUrl = ""
$CodexExe = "codex"
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$DigestModel = "gpt-5.6-luna"
$DigestReasoningEffort = "low"
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexExe) { $CodexExe = [string]$LocalConfig.CodexExe }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.DigestModel) { $DigestModel = [string]$LocalConfig.DigestModel }
    if ($LocalConfig.DigestReasoningEffort) { $DigestReasoningEffort = [string]$LocalConfig.DigestReasoningEffort }
}
# Encodes model + rubric version so x_route_decisions predictors stay
# analyzable across upgrades (plan 019's maintenance note).
$PredictorName = "codex-$($DigestModel -replace '[^a-z0-9]', '')-rubric2"

function Send-DiscordNotification {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ([string]::IsNullOrWhiteSpace($DiscordWebhookUrl)) {
        return
    }
    try {
        $Payload = @{ content = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $DiscordWebhookUrl -Method Post `
            -ContentType "application/json" -Body $Payload | Out-Null
    }
    catch {
        $NotificationError = "Discord notification failed: $($_.Exception.Message)"
        Write-Warning $NotificationError
        $NotificationError | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
}

$Runbook = if ($Slot -eq "weekly") { "docs/x_pipeline/WEEKLY.md" } else { "docs/x_pipeline/DIGESTER.md" }

$Prompt = @"
You are an unattended, non-interactive session launched by Windows Task Scheduler. No human will respond to prompts or approve actions this turn.

Follow $Runbook exactly for slot=$Slot. Use predictor/session name '$PredictorName' wherever the runbook calls for one (e.g. the route --predictor argument). Run repository commands with the `python` on PATH from the repository root.

If the runbook's first step reports a calendar no-op, stop immediately -- that is a normal, expected outcome, not an error.

The rubric requires judging images. Download them with `python -m app.x.run media --run <run_id>` (never curl or Invoke-WebRequest; they have no TLS credentials in this sandbox), then open files under the run's media folder with your image viewing tool. Never skip a post because its substance is in an image. If the cycle reports the run is stuck with status exported, an earlier session already exported it; continue from step 2 on that run.

Hard limits for this session: write only under data/. Never run git. Never edit docs/, app/, ops/, plans/, or the roster. Never use a broker or trading tool. Never continue into investment reasoning.

Do not ask the user any questions, do not wait for confirmation, and do not attempt anything outside the runbook's steps. Complete every applicable step or stop and clearly state what blocked you.
"@

Set-Location $RepoRoot
"=== $Timestamp slot=$Slot model=$DigestModel predictor=$PredictorName ===" | Out-File -FilePath $LogFile -Encoding utf8

$env:CODEX_HOME = $CodexHome
$SessionOutput = @(
    $Prompt | & $CodexExe exec `
        --sandbox workspace-write `
        -C $RepoRoot `
        -m $DigestModel `
        -c "model_reasoning_effort=$DigestReasoningEffort" `
        -c "sandbox_workspace_write.network_access=true" `
        -c "mcp_servers.robinhood-trading.enabled=false" `
        --color never `
        --output-last-message $LastMessageFile `
        - 2>&1
)
$ExitCode = $LASTEXITCODE
$SessionOutput | Out-File -FilePath $LogFile -Append -Encoding utf8
$VerifyOutput = @()
if ($ExitCode -eq 0) {
    $VerifyOutput = @(
        & python -m app.x.run verify --slot $Slot 2>&1
    )
    $ExitCode = $LASTEXITCODE
    $VerifyOutput | Out-File -FilePath $LogFile -Append -Encoding utf8
}
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$CombinedOutput = (@($SessionOutput) + @($VerifyOutput)) -join "`n"
$IsCalendarNoOp = $CombinedOutput -match "calendar no-op"
$HasBudgetWarning = $CombinedOutput -match "budget warning"
$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy digester FAILED: slot=$Slot exit=$ExitCode log=$LogName"
}
elseif (-not $IsCalendarNoOp) {
    $NotificationMessage = "BouStrategy digester completed: slot=$Slot log=$LogName"
    if ($HasBudgetWarning) {
        $NotificationMessage += " WARNING: X read budget threshold reached."
    }
    Send-DiscordNotification $NotificationMessage
}
exit $ExitCode
