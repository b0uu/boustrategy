# Executes policy-approved live order intents during regular market hours.
# One bounded Codex broker session per pending intent follows
# docs/execution/EXECUTOR.md; trusted code then checks the broker ledger
# against the session's report. Safe to run repeatedly: intents that already
# have an execution record are skipped.

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$LocalConfigFile = Join-Path $RepoRoot "ops\digester.local.psd1"

$LogDir = Join-Path $RepoRoot "data\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "execute-$Timestamp.log"

$DiscordWebhookUrl = ""
$CodexHome = Join-Path $HOME ".codex-boustrategy"
$ExecutionModel = "gpt-5.6-sol"
$Profile = "codex"
if (Test-Path -LiteralPath $LocalConfigFile) {
    $LocalConfig = Import-PowerShellDataFile -LiteralPath $LocalConfigFile
    if ($LocalConfig.DiscordWebhookUrl) { $DiscordWebhookUrl = [string]$LocalConfig.DiscordWebhookUrl }
    if ($LocalConfig.CodexHome) { $CodexHome = [string]$LocalConfig.CodexHome }
    if ($LocalConfig.ExecutionModel) { $ExecutionModel = [string]$LocalConfig.ExecutionModel }
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
"=== $Timestamp execute profile=$Profile model=$ExecutionModel ===" | Out-File -FilePath $LogFile -Encoding utf8

$env:CODEX_HOME = $CodexHome
$Output = @(
    & python -m app.broker.executor --profile $Profile --model $ExecutionModel --codex-home $CodexHome `
        --logs data/logs/broker --max-intents 3 2>&1
)
$ExitCode = $LASTEXITCODE
$Output | Out-File -FilePath $LogFile -Append -Encoding utf8
"--- exit code: $ExitCode ---" | Out-File -FilePath $LogFile -Append -Encoding utf8

$Summary = ($Output | Where-Object { $_ -like '{"executed"*' } | Select-Object -Last 1)
$LogName = Split-Path -Leaf $LogFile
if ($ExitCode -ne 0) {
    Send-DiscordNotification "BouStrategy live execution needs ATTENTION: exit=$ExitCode log=$LogName`n$($Summary.ToString().Substring(0, [Math]::Min(900, $Summary.ToString().Length)))"
}
elseif ($Summary -and $Summary -notlike '{"executed": []}') {
    Send-DiscordNotification "BouStrategy live execution completed: log=$LogName`n$($Summary.ToString().Substring(0, [Math]::Min(900, $Summary.ToString().Length)))"
}
exit $ExitCode
