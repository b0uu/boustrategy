# Registers the five Windows Task Scheduler triggers from plan 019's ops
# note: three weekday digester slots, a half-day close covering trigger,
# and the Sunday weekly consolidation. Run once, interactively, as the
# account that should own these tasks. Re-running is safe -- each task is
# replaced (Register-ScheduledTask -Force) rather than duplicated.
#
# The 14:45 ET trigger only does real work on NYSE half-days (Thanksgiving
# Friday, Christmas eve in 2026); on every other weekday it hits `cycle`,
# which is calendar-aware and no-ops cleanly (see plan 018). The 17:45 ET
# trigger correspondingly no-ops ON half-days. This lets a naive
# every-weekday schedule stay correct without special-casing specific
# dates here.

# Tasks run in the interactive Administrator session with highest privileges.
# Codex's Windows sandbox runner cannot start under a non-interactive
# (password/batch) logon: it times out connecting its runner pipe. Keep the
# server session signed in (disconnect RDP, never sign out).

param([switch]$Enable)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$ScriptPath = Join-Path $RepoRoot "ops\run-digester-session.ps1"

function New-DigesterTask {
    param(
        [string]$Name,
        [string]$Slot,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger,
        [switch]$HalfDayOnly
    )
    $Extra = if ($HalfDayOnly) { " -HalfDayOnly" } else { "" }
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -Slot $Slot$Extra" `
        -WorkingDirectory $RepoRoot
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew `
        -Disable:(-not $Enable)
    $Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger `
        -Settings $Settings -Description "boustrategy X pipeline: $Slot slot (plan 019)" -Principal $Principal -Force | Out-Null
    Write-Output "Registered: $Name"
}

$Weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

New-DigesterTask -Name "boustrategy-digester-morning" -Slot "morning" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 08:45)

New-DigesterTask -Name "boustrategy-digester-midday" -Slot "midday" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 12:30)

New-DigesterTask -Name "boustrategy-digester-close-halfday" -Slot "close" -HalfDayOnly `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 14:45)

New-DigesterTask -Name "boustrategy-digester-close" -Slot "close" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 17:45)

New-DigesterTask -Name "boustrategy-digester-weekly" -Slot "weekly" `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 18:00)

Write-Output "`nAll five tasks registered. Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'boustrategy-digester-*' | Select TaskName,State"
