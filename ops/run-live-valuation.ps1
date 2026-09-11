# Takes one read-only broker valuation during the regular session so the public
# dashboard can show a fresh observation every 15 minutes.
#
# The scheduled task only wakes this wrapper; app.broker.valuation is the authority on
# whether the tick may observe (NYSE calendar, half-days, DST) and holds the overlap
# lock. It runs only the collector's fingerprint-checked `snapshot` command through the
# bot's Codex identity and never preflight, review or order tools. A failed tick writes
# nothing, so the last good observation remains the public value.
#
# -WhatIf prints the session decision and the sanitized command shape. It starts no
# model session, writes no row and leaves no log.

param(
    [switch]$WhatIf
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$PublicConfigFile = Join-Path $RepoRoot "ops\public.local.psd1"

$DiscordWebhookUrl = ""
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$CollectorModel = "gpt-5.6-luna"
$LiveProfile = "codex"
$TimeoutSeconds = 480
$AlertAfter = 3
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.CollectorModel) { $CollectorModel = [string]$LocalConfig.CollectorModel }
    if ($LocalConfig.LiveProfile) { $LiveProfile = [string]$LocalConfig.LiveProfile }
}
if (Test-Path -LiteralPath $PublicConfigFile) {
    $PublicConfig = Import-PowerShellDataFile -LiteralPath $PublicConfigFile
    if ($PublicConfig.ValuationTimeoutSeconds) { $TimeoutSeconds = [int]$PublicConfig.ValuationTimeoutSeconds }
    if ($PublicConfig.ValuationAlertAfter) { $AlertAfter = [int]$PublicConfig.ValuationAlertAfter }
}

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "valuation-$Timestamp.log"

function Write-Log {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    if ($WhatIf) { Write-Output $Line; return }
    $Line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Send-DiscordNotification {
    param([Parameter(Mandatory = $true)][string]$Message)

    if ($WhatIf -or [string]::IsNullOrWhiteSpace($DiscordWebhookUrl)) {
        return
    }
    try {
        $Payload = @{ content = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $DiscordWebhookUrl -Method Post `
            -ContentType "application/json" -Body $Payload | Out-Null
    }
    catch {
        Write-Log "Discord notification failed: $($_.Exception.GetType().Name)"
    }
}

Set-Location $RepoRoot
if (-not $WhatIf) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
Write-Log "=== $Timestamp live valuation profile=$LiveProfile model=$CollectorModel ==="

# The valuation is the lowest-priority broker session. When a review preparation, a
# review tick or an execution is already running, skip this tick rather than start a
# second session on the same Codex identity; the next tick is 15 minutes away.
$Busy = @(
    Get-ScheduledTask -TaskName "boustrategy-live-execute", "boustrategy-review-*" -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Running" } | ForEach-Object { $_.TaskName }
)
if ($Busy.Count -gt 0) {
    Write-Log ("deferred: broker task running ({0})" -f ($Busy -join ", "))
    if (-not $WhatIf) { exit 0 }
}

$env:CODEX_HOME = $CodexHome
$Arguments = @(
    "-m", "app.broker.valuation",
    "--profile", $LiveProfile,
    "--model", $CollectorModel,
    "--codex-home", $CodexHome,
    "--timeout", $TimeoutSeconds,
    "--alert-after", $AlertAfter
)
if ($WhatIf) { $Arguments += "--what-if" }

$Started = Get-Date
$Output = @(& python @Arguments 2>&1)
$ExitCode = $LASTEXITCODE
$Elapsed = [math]::Round(((Get-Date) - $Started).TotalSeconds, 1)
if (-not $WhatIf) { $Output | Out-File -FilePath $LogFile -Append -Encoding utf8 }

$ResultLine = $Output | ForEach-Object { "$_" } | Where-Object { $_ -like '{*' } | Select-Object -Last 1
if ($WhatIf) { Write-Output $ResultLine }
Write-Log "--- exit code: $ExitCode elapsed=${Elapsed}s ---"

$Alert = $null
if ($ResultLine) {
    try { $Alert = ($ResultLine | ConvertFrom-Json).alert } catch { $Alert = $null }
}
elseif ($ExitCode -ne 0) {
    $Alert = "BouStrategy valuation FAILED before a result: exit=$ExitCode log=$(Split-Path -Leaf $LogFile)"
}
if ($Alert) { Send-DiscordNotification ([string]$Alert) }
exit $ExitCode
