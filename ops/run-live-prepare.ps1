# Prepares the live investment review after the close digest: refreshes prices,
# regime, calendar and triggers through the deterministic paper preparation,
# then captures a fresh broker snapshot through the bot's Codex identity and
# creates the PREPARED live reasoning run the scheduler consumes.
#
# One task per review slot; each may carry several triggers because the
# schedule revision decides whether this slot is actually due today.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("midday", "preclose", "close")]
    [string]$Slot
)

$ScheduleId = "live-$Slot"

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "prepare-live-$Slot-$Timestamp.log"

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
"=== $Timestamp prepare-live slot=$Slot schedule=$ScheduleId profile=$Profile ===" | Out-File -FilePath $LogFile -Encoding utf8

# The schedule revision in SQLite owns the due time, including half-day handling and
# whether this slot runs at all. Asking it keeps one task able to carry several
# triggers without preparing a session that is not actually due.
$Lookup = & python -c "import sys; from datetime import datetime; from zoneinfo import ZoneInfo; from app.storage.database import connect; from app.storage.schedules import latest_schedule, due_at; c = connect('data/boustrategy.db'); s = latest_schedule(c, sys.argv[1]); d = datetime.now(ZoneInfo('America/New_York')).date(); due = due_at(s, d) if s else None; print(d.isoformat(), due.isoformat() if due else 'none')" $ScheduleId
if ($LASTEXITCODE -ne 0) {
    "schedule lookup failed" | Out-File -FilePath $LogFile -Append -Encoding utf8
    Send-DiscordNotification "BouStrategy prepare-live FAILED: schedule lookup, log=$(Split-Path -Leaf $LogFile)"
    exit 1
}
$SessionDate, $DueText = $Lookup.Trim().Split(" ")
if ($DueText -eq "none") {
    "$SessionDate has no ${ScheduleId} occurrence: calendar no-op" | Out-File -FilePath $LogFile -Append -Encoding utf8
    exit 0
}
$Minutes = ([datetimeoffset]::Parse($DueText) - [datetimeoffset]::Now).TotalMinutes
if ($Minutes -gt 45 -or $Minutes -lt -15) {
    "$ScheduleId is due $DueText, {0:N0} minutes away: wrong trigger, no-op" -f $Minutes |
        Out-File -FilePath $LogFile -Append -Encoding utf8
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
$LiveOut = "data/reason_runs/$SessionDate-live-$Slot"
$Output = @(
    & python -m app.broker.collector --profile $Profile --model $CollectorModel --codex-home $CodexHome `
        prepare-live --slot $Slot --model-label $ReviewModel --out $LiveOut --date $SessionDate 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy prepare-live FAILED: slot=$Slot date=$SessionDate exit=$ExitCode log=$LogName"
}
else {
    Send-DiscordNotification "BouStrategy prepare-live completed: slot=$Slot date=$SessionDate $($Output[-1])"
}
exit $ExitCode
