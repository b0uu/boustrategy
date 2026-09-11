# Supervises continuous publication from the private source into the public read model.
#
# Profiles are derived exactly like publish-public.ps1: only enabled, account-bound
# profiles from the gitignored ops\live.local.json. Profile IDs and fingerprints are
# private producer inputs, so neither they nor the argument list are logged.
#
# The watcher publishes every 5 seconds and prints a summary line per pass; only passes
# that changed something are logged. An unexpected exit is logged, alerted and
# restarted with backoff. Five exits within 15 minutes ends the supervisor with a
# nonzero code so Task Scheduler records the failure and the health task alerts.
# This script never starts the public server or any trading schedule.

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$ProfilesFile = Join-Path $RepoRoot "ops\live.local.json"
$SourceDb = Join-Path $RepoRoot "data\boustrategy.db"
$PublicDb = Join-Path $RepoRoot "data\boustrategy.public.db"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "publication-watch-$Timestamp.log"

$DiscordWebhookUrl = ""
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
}

function Write-Log {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Line)
    "$(Get-Date -Format o) $Line" | Out-File -FilePath $LogFile -Append -Encoding utf8
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
        Write-Log "Discord notification failed: $($_.Exception.GetType().Name)"
    }
}

Set-Location $RepoRoot
Write-Log "=== publication watch supervisor started ==="

$PublishArgs = @()
$Included = 0
if (Test-Path -LiteralPath $ProfilesFile) {
    $Config = Get-Content -LiteralPath $ProfilesFile -Raw | ConvertFrom-Json
    foreach ($Profile in $Config.profiles) {
        if ($Profile.enabled -and $Profile.broker_account_fingerprint) {
            $PublishArgs += @(
                "--live-profile", $Profile.execution_profile_id,
                "--live-account-id", $Profile.broker_account_fingerprint
            )
            $Included += 1
        }
    }
}
Write-Log "live profiles included: $Included"

# A watcher orphaned by a stopped task would keep writing beside a new one.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'app\.public\.publication' -and $_.CommandLine -match '--watch' } |
    ForEach-Object {
        Write-Log "stopping orphaned publication watcher pid=$($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

$Exits = @()
while ($true) {
    $Started = Get-Date
    & python -m app.public.publication --source $SourceDb --public-db $PublicDb @PublishArgs --watch 5 2>&1 |
        ForEach-Object {
            $Line = "$_"
            if ($Line -notlike '{*' -or $Line -notlike '*"inserted": 0, "updated": 0, "withdrawn": 0*') {
                Write-Log $Line
            }
        }
    $ExitCode = $LASTEXITCODE
    $Ran = [math]::Round(((Get-Date) - $Started).TotalSeconds)
    Write-Log "publication watcher exited unexpectedly: exit=$ExitCode after ${Ran}s"
    $Now = Get-Date
    $Exits = @($Exits | Where-Object { $_ -gt $Now.AddMinutes(-15) }) + $Now
    if ($Exits.Count -ge 5) {
        Send-DiscordNotification "BouStrategy publisher stopped after $($Exits.Count) exits in 15 minutes: exit=$ExitCode log=$(Split-Path -Leaf $LogFile)"
        Write-Log "giving up after $($Exits.Count) exits in 15 minutes"
        if ($ExitCode -eq 0) { exit 1 }
        exit $ExitCode
    }
    Send-DiscordNotification "BouStrategy publisher exited unexpectedly: exit=$ExitCode; restarting log=$(Split-Path -Leaf $LogFile)"
    Start-Sleep -Seconds ([math]::Min(60, 5 * $Exits.Count))
}
