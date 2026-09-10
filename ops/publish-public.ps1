# Publishes the private source into the separate public read model.
#
# The live profile IDs and their broker account fingerprints are private producer
# inputs, so they are read from the gitignored ops\live.local.json rather than
# written into a committed script or a task argument. Only enabled, account-bound
# profiles are included, which keeps a disabled profile out of the public store.

param(
    [switch]$Quiet
)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$ProfilesFile = Join-Path $RepoRoot "ops\live.local.json"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "publish-$Timestamp.log"

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
"=== $Timestamp publish ===" | Out-File -FilePath $LogFile -Encoding utf8

$PublishArgs = @()
if (Test-Path -LiteralPath $ProfilesFile) {
    $Config = Get-Content -LiteralPath $ProfilesFile -Raw | ConvertFrom-Json
    foreach ($Profile in $Config.profiles) {
        if ($Profile.enabled -and $Profile.broker_account_fingerprint) {
            $PublishArgs += @(
                "--live-profile", $Profile.execution_profile_id,
                "--live-account-id", $Profile.broker_account_fingerprint
            )
        }
    }
}

$Output = @(
    & python -m app.public.publication --source data/boustrategy.db `
        --public-db data/boustrategy.public.db @PublishArgs 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$Summary = ($Output | Where-Object { $_ -like '{*' } | Select-Object -Last 1)
if (-not $Quiet) { Write-Output $Summary }
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy publication FAILED: exit=$ExitCode log=$(Split-Path -Leaf $LogFile)"
}
elseif ($Summary -and $Summary -notlike '*"inserted": 0, "updated": 0, "withdrawn": 0*') {
    Send-DiscordNotification "BouStrategy published: $Summary"
}
exit $ExitCode
