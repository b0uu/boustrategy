# Supervises the read-only public origin on 127.0.0.1:8380 behind the Cloudflare Tunnel.
#
# The server starts only when the public store is a readable, non-WAL SQLite file that
# passes a quick integrity check and the built browser bundle exists. It binds loopback
# only; cloudflared is the sole path in from the internet. --behind-tunnel lets request
# limits key on Cloudflare's client address for loopback peers.
#
# An unexpected exit is logged, alerted and restarted with backoff. Five exits within
# 15 minutes ends the supervisor with a nonzero code. This script never starts the
# publisher, the tunnel or any trading schedule.

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$PublicConfigFile = Join-Path $RepoRoot "ops\public.local.psd1"
$PublicDb = Join-Path $RepoRoot "data\boustrategy.public.db"
$FrontendIndex = Join-Path $RepoRoot "public-ui\dist\index.html"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "public-server-$Timestamp.log"

$DiscordWebhookUrl = ""
$Port = 8380
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
}
if (Test-Path -LiteralPath $PublicConfigFile) {
    $PublicConfig = Import-PowerShellDataFile -LiteralPath $PublicConfigFile
    if ($PublicConfig.PublicPort) { $Port = [int]$PublicConfig.PublicPort }
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

function Stop-WithFailure {
    param([string]$Reason)
    Write-Log "refusing to start: $Reason"
    Send-DiscordNotification "BouStrategy public server did not start: $Reason log=$(Split-Path -Leaf $LogFile)"
    exit 1
}

Set-Location $RepoRoot
Write-Log "=== public server supervisor started port=$Port ==="

if (-not (Test-Path -LiteralPath $FrontendIndex)) { Stop-WithFailure "built bundle missing" }
if (-not (Test-Path -LiteralPath $PublicDb)) { Stop-WithFailure "public store missing" }
$Check = & python -c "import sqlite3, sys, pathlib; p = pathlib.Path(sys.argv[1]); wal = p.open('rb').read(20)[18:20] == bytes([2, 2]); c = sqlite3.connect(p.resolve().as_uri() + '?mode=ro', uri=True); r = c.execute('pragma quick_check').fetchone()[0]; c.close(); print('wal' if wal else r)" $PublicDb 2>&1
if ($LASTEXITCODE -ne 0 -or "$Check" -ne "ok") { Stop-WithFailure "public store check failed ($(if ("$Check" -eq 'wal') { 'wal' } else { 'integrity' }))" }

# A server orphaned by a stopped task still holds the port; anything else holding it is
# not ours to stop.
$Holders = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($HolderId in $Holders) {
    $Holder = Get-CimInstance Win32_Process -Filter "ProcessId=$HolderId" -ErrorAction SilentlyContinue
    if ($Holder -and $Holder.CommandLine -match 'app\.public\.server') {
        Write-Log "stopping orphaned public server pid=$HolderId"
        Stop-Process -Id $HolderId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    else {
        Stop-WithFailure "port $Port is held by another process"
    }
}

$Exits = @()
while ($true) {
    $Started = Get-Date
    & python -m app.public.server --public-db $PublicDb --port $Port --behind-tunnel 2>&1 |
        ForEach-Object { Write-Log "$_" }
    $ExitCode = $LASTEXITCODE
    $Ran = [math]::Round(((Get-Date) - $Started).TotalSeconds)
    Write-Log "public server exited unexpectedly: exit=$ExitCode after ${Ran}s"
    $Now = Get-Date
    $Exits = @($Exits | Where-Object { $_ -gt $Now.AddMinutes(-15) }) + $Now
    if ($Exits.Count -ge 5) {
        Send-DiscordNotification "BouStrategy public server stopped after $($Exits.Count) exits in 15 minutes: exit=$ExitCode log=$(Split-Path -Leaf $LogFile)"
        Write-Log "giving up after $($Exits.Count) exits in 15 minutes"
        if ($ExitCode -eq 0) { exit 1 }
        exit $ExitCode
    }
    Send-DiscordNotification "BouStrategy public server exited unexpectedly: exit=$ExitCode; restarting log=$(Split-Path -Leaf $LogFile)"
    Start-Sleep -Seconds ([math]::Min(60, 5 * $Exits.Count))
}
