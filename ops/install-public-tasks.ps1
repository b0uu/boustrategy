# Registers the four public-dashboard tasks. Each is created Disabled unless -Enable is
# passed, and -Enable enables only these four. The existing digester, review and
# execution tasks are never touched. Task arguments carry no credentials; wrappers read
# private inputs from gitignored files at run time.
#
# Run once, interactively, as the account that owns the trading tasks. Re-running
# replaces each of these four tasks (Register-ScheduledTask -Force).
#
# The valuation runs Codex, so it needs the same interactive, highest-privilege
# principal as the digester and review tasks (the Codex sandbox runner fails under a
# batch logon). The publisher, server and health check need no elevation.
#
# Valuation ticks fall at :07, :22, :37 and :52. That keeps them off the :00/:15/:30/:45
# grid where review preparation (12:45, 14:45) and execution ticks start their own
# broker sessions on the same Codex identity; the wrapper also skips a tick while one of
# those tasks is running. The wrapper, not these triggers, decides whether a tick is
# inside an actual regular session (holidays, half-days, DST).

param([switch]$Enable)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$Weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$UserId = "$env:USERDOMAIN\$env:USERNAME"

function Register-PublicTask {
    param(
        [string]$Name,
        [string]$Script,
        [string]$Arguments = "",
        [Microsoft.Management.Infrastructure.CimInstance[]]$Triggers,
        [TimeSpan]$TimeLimit,
        [string]$RunLevel,
        [switch]$Restart,
        [string]$Description
    )
    $ScriptPath = Join-Path $RepoRoot "ops\$Script"
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $Arguments".TrimEnd() `
        -WorkingDirectory $RepoRoot
    $SettingsArgs = @{
        StartWhenAvailable         = $true
        DontStopOnIdleEnd          = $true
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimit         = $TimeLimit
        MultipleInstances          = "IgnoreNew"
        Disable                    = (-not $Enable)
    }
    if ($Restart) {
        $SettingsArgs.RestartCount = 999
        $SettingsArgs.RestartInterval = New-TimeSpan -Minutes 1
    }
    $Settings = New-ScheduledTaskSettingsSet @SettingsArgs
    $Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel $RunLevel
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Triggers `
        -Settings $Settings -Description $Description -Principal $Principal -Force | Out-Null
    Write-Output ("Registered: {0} ({1})" -f $Name, $(if ($Enable) { "enabled" } else { "disabled" }))
}

function New-RepeatingTrigger {
    param([Microsoft.Management.Infrastructure.CimInstance]$Trigger, [TimeSpan]$Interval, [TimeSpan]$Duration)
    $Template = if ($Duration -gt [TimeSpan]::Zero) {
        New-ScheduledTaskTrigger -Once -At 00:00 -RepetitionInterval $Interval -RepetitionDuration $Duration
    }
    else {
        New-ScheduledTaskTrigger -Once -At 00:00 -RepetitionInterval $Interval
    }
    $Trigger.Repetition = $Template.Repetition
    return $Trigger
}

$Unlimited = [TimeSpan]::Zero

Register-PublicTask -Name "boustrategy-public-server" -Script "run-public-server.ps1" `
    -Triggers @((New-ScheduledTaskTrigger -AtLogOn -User $UserId)) `
    -TimeLimit $Unlimited -RunLevel Limited -Restart `
    -Description "boustrategy public dashboard: read-only origin on 127.0.0.1:8380 behind the Cloudflare Tunnel"

Register-PublicTask -Name "boustrategy-public-publisher" -Script "run-publication-watch.ps1" `
    -Triggers @((New-ScheduledTaskTrigger -AtLogOn -User $UserId)) `
    -TimeLimit $Unlimited -RunLevel Limited -Restart `
    -Description "boustrategy public dashboard: continuous publication into the public store"

# One repeating trigger from registration plus one at logon, so checks resume after a
# reboot without waiting for the next whole interval.
$HealthTriggers = @(
    (New-RepeatingTrigger -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1)) `
        -Interval (New-TimeSpan -Minutes 5) -Duration $Unlimited),
    (New-RepeatingTrigger -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $UserId) `
        -Interval (New-TimeSpan -Minutes 5) -Duration $Unlimited)
)
Register-PublicTask -Name "boustrategy-public-health" -Script "check-public-health.ps1" -Arguments "-Quiet" `
    -Triggers $HealthTriggers -TimeLimit (New-TimeSpan -Minutes 4) -RunLevel Limited `
    -Description "boustrategy public dashboard: health, integrity, publication lag and tunnel checks"

Register-PublicTask -Name "boustrategy-live-valuation" -Script "run-live-valuation.ps1" `
    -Triggers @(New-RepeatingTrigger -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 09:37) `
        -Interval (New-TimeSpan -Minutes 15) -Duration (New-TimeSpan -Hours 6 -Minutes 30)) `
    -TimeLimit (New-TimeSpan -Minutes 12) -RunLevel Highest `
    -Description "boustrategy live valuation: read-only broker snapshot every 15 minutes in the regular session"

Write-Output "`nFour tasks registered. Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'boustrategy-public-*','boustrategy-live-valuation' | Select TaskName,State"
