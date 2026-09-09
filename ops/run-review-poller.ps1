# One tick of the paper investment-review scheduler. Task Scheduler runs
# this every minute through the due/grace window; the persisted runtime
# decides whether anything is due, waits on missing prerequisites, claims
# at most one occurrence, and launches Codex exactly once per occurrence.
# The task must use IgnoreNew so a long authoring run isn't overlapped;
# the runtime's account lease guards against overlap from any other caller.

param(
    [string]$Schedule = "paper-close"
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Day = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "poller-$Schedule-$Day.log"

$DiscordWebhookUrl = ""
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$ReviewModel = "gpt-5.6-sol"
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.ReviewModel) { $ReviewModel = [string]$LocalConfig.ReviewModel }
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
$SessionDate = & python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('America/New_York')).date().isoformat())"
$Receipt = "data/reason_runs/$SessionDate/preparation.json"

$Timestamp = Get-Date -Format "HH:mm:ss"
"=== $Timestamp tick schedule=$Schedule model=$ReviewModel receipt=$Receipt ===" | Out-File -FilePath $LogFile -Append -Encoding utf8

$env:CODEX_HOME = $CodexHome
$Output = @(
    & python -m app.reason.runtime --db data/boustrategy.db scheduled `
        --schedule $Schedule `
        --model $ReviewModel `
        --paper-preparation $Receipt `
        --digest-dir data/digests `
        --out data/runtime-intakes `
        --logs data/runtime-logs 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$Combined = $Output -join "`n"
$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy review poller FAILED: schedule=$Schedule exit=$ExitCode log=$LogName"
}
elseif ($Combined -match '"run_id"') {
    # Only a tick that claimed, ran or refused an actual run is worth a message;
    # nothing-due, waiting and overlap ticks stay in the log.
    Send-DiscordNotification "BouStrategy review tick: schedule=$Schedule log=$LogName`n$($Combined.Substring(0, [Math]::Min(600, $Combined.Length)))"
}
exit $ExitCode
