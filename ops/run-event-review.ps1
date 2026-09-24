# Starts an event review when something between scheduled reviews can't wait: crisis mode
# switching on, or a holding gaining a mandatory reason. app.reason.events decides; a check that
# finds nothing prints {"cause": null} and starts no model session.

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"
$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "event-review-$(Get-Date -Format 'yyyy-MM-dd').log"

$DiscordWebhookUrl = ""
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$ReviewModel = "gpt-5.6-sol"
$CollectorModel = "gpt-5.6-luna"
$Profile = "codex"
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.ReviewModel) { $ReviewModel = [string]$LocalConfig.ReviewModel }
    if ($LocalConfig.CollectorModel) { $CollectorModel = [string]$LocalConfig.CollectorModel }
    if ($LocalConfig.LiveProfile) { $Profile = [string]$LocalConfig.LiveProfile }
}

Set-Location $RepoRoot
$env:CODEX_HOME = $CodexHome
$Output = @(
    & python -m app.reason.events --profile $Profile --model $ReviewModel `
        --collector-model $CollectorModel 2>&1
)
$ExitCode = $LASTEXITCODE
"=== $(Get-Date -Format 'HH:mm:ss') exit=$ExitCode ===" | Out-File -FilePath $LogFile -Append -Encoding utf8
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8

$Combined = $Output -join "`n"
if (-not [string]::IsNullOrWhiteSpace($DiscordWebhookUrl) -and
    ($ExitCode -ne 0 -or $Combined -notmatch '"cause": null')) {
    $Message = if ($ExitCode -ne 0) { "BouStrategy event review FAILED: exit=$ExitCode" } `
        else { "BouStrategy event review: $($Combined.Substring(0, [Math]::Min(400, $Combined.Length)))" }
    try {
        $Payload = @{ content = $Message } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $DiscordWebhookUrl -Method Post -ContentType "application/json" `
            -Body $Payload | Out-Null
    }
    catch {
        "Discord notification failed: $($_.Exception.Message)" |
            Out-File -FilePath $LogFile -Append -Encoding utf8
    }
}
exit $ExitCode
