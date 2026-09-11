# Checks the public stack every few minutes and alerts only when its state changes.
#
# Checks: the local health endpoint answers ok; the public store is a non-WAL file that
# passes a quick integrity check; publication keeps up with the private source; the
# origin listens on loopback only; the publisher and server tasks are running when
# enabled (a stopped one is started again); and the cloudflared service is running
# when installed. A disabled task is deliberate and is not restarted.
#
# State lives in data\state\public-health.json and one log per day. The alert text
# names failing checks only, never paths, identifiers or response bodies.

param(
    [switch]$Quiet
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$PublicConfigFile = Join-Path $RepoRoot "ops\public.local.psd1"
$StateFile = Join-Path $RepoRoot "data\state\public-health.json"

$DiscordWebhookUrl = ""
$Port = 8380
$SettleSeconds = 30
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
}
if (Test-Path -LiteralPath $PublicConfigFile) {
    $PublicConfig = Import-PowerShellDataFile -LiteralPath $PublicConfigFile
    if ($PublicConfig.PublicPort) { $Port = [int]$PublicConfig.PublicPort }
    if ($PublicConfig.PublicationSettleSeconds) { $SettleSeconds = [int]$PublicConfig.PublicationSettleSeconds }
}

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir, (Split-Path $StateFile) | Out-Null
$LogFile = Join-Path $LogDir ("public-health-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

function Write-Log {
    param([Parameter(Mandatory = $true)][string]$Line)
    "$(Get-Date -Format o) $Line" | Out-File -FilePath $LogFile -Append -Encoding utf8
    if (-not $Quiet) { Write-Output $Line }
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
$Checks = [ordered]@{}
$Notes = @()

# Supervisor tasks first, so a restart has a moment to bind before the HTTP check.
foreach ($TaskName in "boustrategy-public-server", "boustrategy-public-publisher") {
    $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $Task -or $Task.State -eq "Disabled") { continue }
    $Short = $TaskName -replace '^boustrategy-public-', ''
    if ($Task.State -ne "Running") {
        Start-ScheduledTask -TaskName $TaskName
        $Notes += "started $Short task"
        Start-Sleep -Seconds 5
        $Task = Get-ScheduledTask -TaskName $TaskName
    }
    $Checks["${Short}_task"] = $Task.State -eq "Running"
}

try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/public/v2/health" -TimeoutSec 10
    $Checks["http"] = $Health.status -eq "ok"
    $Notes += "age=$($Health.age_seconds)s revision=$($Health.revision)"
}
catch {
    $Checks["http"] = $false
    $Status = $null
    if ($_.Exception.Response) { $Status = [int]$_.Exception.Response.StatusCode }
    $Notes += "http=$(if ($Status) { $Status } else { 'unreachable' })"
}

$ProbeLine = & python -m app.public.monitor --settle $SettleSeconds 2>$null |
    Where-Object { $_ -like '{*' } | Select-Object -Last 1
$Probe = $null
if ($ProbeLine) { try { $Probe = $ProbeLine | ConvertFrom-Json } catch { $Probe = $null } }
$Checks["store"] = [bool]($Probe -and $Probe.public_integrity -eq "ok" -and $Probe.public_wal -eq $false)
$Checks["publication"] = [bool]($Probe -and $Probe.publication -eq "current")
if ($Probe) { $Notes += "publication=$($Probe.publication) lag=$($Probe.lag_seconds)s" }

$Listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
$Checks["loopback_only"] = $Listeners.Count -gt 0 -and
    @($Listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }).Count -eq 0

$Tunnel = Get-Service -Name cloudflared -ErrorAction SilentlyContinue
if ($Tunnel) { $Checks["tunnel"] = $Tunnel.Status -eq "Running" }

$Failing = @($Checks.Keys | Where-Object { -not $Checks[$_] })
$Previous = @()
if (Test-Path -LiteralPath $StateFile) {
    try { $Previous = @((Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json).failing) } catch { $Previous = @() }
}
$Previous = @($Previous | Where-Object { $_ })
$Summary = if ($Failing.Count) { "FAILING: $($Failing -join ', ')" } else { "ok" }
Write-Log "$Summary; $($Notes -join '; ')"

$Changed = (@(Compare-Object -ReferenceObject $Previous -DifferenceObject $Failing -ErrorAction SilentlyContinue)).Count -gt 0 -or
    ($Previous.Count -ne $Failing.Count)
if ($Changed) {
    if ($Failing.Count -eq 0) {
        Send-DiscordNotification "BouStrategy public stack recovered: all checks ok"
    }
    else {
        Send-DiscordNotification "BouStrategy public stack $Summary"
    }
}
@{ failing = $Failing; checked_at = (Get-Date).ToUniversalTime().ToString("o") } |
    ConvertTo-Json -Compress | Out-File -FilePath $StateFile -Encoding utf8

if ($Failing.Count) { exit 1 }
exit 0
