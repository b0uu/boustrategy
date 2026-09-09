# Builds today's paper preparation receipt after the close digest has landed.
# Deterministic: no model, no X reads, no broker. It refuses to run when the
# same-day digest is missing, which is the loud failure the review poller
# then reports as a missing prerequisite.
#
# -Window close   : normal sessions, run after the 17:45 digest.
# -Window halfday : early-close sessions, run after the 14:45 digest.
# On a day that doesn't match the window the script no-ops so one weekday
# schedule stays correct without special-casing dates.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("close", "halfday")]
    [string]$Window
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "prepare-$Window-$Timestamp.log"

$DiscordWebhookUrl = ""
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
}

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
        "Discord notification failed: $($_.Exception.Message)" | Out-File -FilePath $LogFile -Append -Encoding utf8
    }
}

Set-Location $RepoRoot
"=== $Timestamp prepare window=$Window ===" | Out-File -FilePath $LogFile -Encoding utf8

# Prints "<date> full", "<date> half" or "<date> none" for today's New York session.
$SessionInfo = & python -c "from datetime import datetime; from zoneinfo import ZoneInfo; from app.x.calendar import run_slots; d = datetime.now(ZoneInfo('America/New_York')).date(); s = run_slots(d); print(d.isoformat(), 'none' if not s else ('half' if len(s) == 2 else 'full'))"
if ($LASTEXITCODE -ne 0) {
    "calendar lookup failed" | Out-File -FilePath $LogFile -Append -Encoding utf8
    Send-DiscordNotification "BouStrategy prepare FAILED: calendar lookup, log=$(Split-Path -Leaf $LogFile)"
    exit 1
}
$SessionDate, $SessionKind = $SessionInfo.Trim().Split(" ")
$Expected = if ($Window -eq "halfday") { "half" } else { "full" }
if ($SessionKind -ne $Expected) {
    "$SessionDate is $SessionKind; window=${Window}: calendar no-op" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 0
}

$OutDir = "data/reason_runs/$SessionDate"
$Output = @(
    & python -m app.reason.run prepare --date $SessionDate --out $OutDir 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $RepoRoot "$OutDir\preparation.json"))) {
    if ($ExitCode -eq 0) { $ExitCode = 1 }
    Send-DiscordNotification "BouStrategy prepare FAILED: date=$SessionDate exit=$ExitCode log=$LogName"
}
else {
    Send-DiscordNotification "BouStrategy prepare completed: date=$SessionDate receipt=$OutDir/preparation.json"
}
exit $ExitCode
