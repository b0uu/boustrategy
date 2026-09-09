# Prepares the live investment review after the close digest: refreshes prices,
# regime, calendar and triggers through the deterministic paper preparation,
# then captures a fresh broker snapshot through the bot's Codex identity and
# creates the PREPARED live reasoning run the scheduler consumes.
#
# -Window close   : normal sessions, run after the 17:45 digest.
# -Window halfday : early-close sessions, run after the 14:45 digest.

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
$LogFile = Join-Path $LogDir "prepare-live-$Window-$Timestamp.log"

$DiscordWebhookUrl = ""
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$CollectorModel = "gpt-5.6-luna"
$ReviewModel = "gpt-5.6-sol"
$Profile = "codex"
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.CollectorModel) { $CollectorModel = [string]$LocalConfig.CollectorModel }
    if ($LocalConfig.ReviewModel) { $ReviewModel = [string]$LocalConfig.ReviewModel }
    if ($LocalConfig.LiveProfile) { $Profile = [string]$LocalConfig.LiveProfile }
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
"=== $Timestamp prepare-live window=$Window profile=$Profile ===" | Out-File -FilePath $LogFile -Encoding utf8

$SessionInfo = & python -c "from datetime import datetime; from zoneinfo import ZoneInfo; from app.x.calendar import run_slots; d = datetime.now(ZoneInfo('America/New_York')).date(); s = run_slots(d); print(d.isoformat(), 'none' if not s else ('half' if len(s) == 2 else 'full'))"
if ($LASTEXITCODE -ne 0) {
    "calendar lookup failed" | Out-File -FilePath $LogFile -Append -Encoding utf8
    Send-DiscordNotification "BouStrategy prepare-live FAILED: calendar lookup, log=$(Split-Path -Leaf $LogFile)"
    exit 1
}
$SessionDate, $SessionKind = $SessionInfo.Trim().Split(" ")
$Expected = if ($Window -eq "halfday") { "half" } else { "full" }
if ($SessionKind -ne $Expected) {
    "$SessionDate is $SessionKind; window=${Window}: calendar no-op" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 0
}

# Step 1: deterministic market preparation (prices, regime, calendar, triggers).
$PaperOut = "data/reason_runs/$SessionDate"
$Output = @(& python -m app.reason.run prepare --date $SessionDate --out $PaperOut 2>&1)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
if ($ExitCode -ne 0) {
    "--- exit code: $ExitCode (market preparation) ---" | Out-File -FilePath $LogFile -Append -Encoding utf8
    Send-DiscordNotification "BouStrategy prepare-live FAILED at market preparation: date=$SessionDate log=$(Split-Path -Leaf $LogFile)"
    exit $ExitCode
}

# Step 2: fresh broker snapshot plus the PREPARED live reasoning run.
$env:CODEX_HOME = $CodexHome
$LiveOut = "data/reason_runs/$SessionDate-live"
$Output = @(
    & python -m app.broker.collector --profile $Profile --model $CollectorModel --codex-home $CodexHome `
        prepare-live --slot close --model-label $ReviewModel --out $LiveOut --date $SessionDate 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy prepare-live FAILED: date=$SessionDate exit=$ExitCode log=$LogName"
}
else {
    Send-DiscordNotification "BouStrategy prepare-live completed: date=$SessionDate $($Output[-1])"
}
exit $ExitCode
