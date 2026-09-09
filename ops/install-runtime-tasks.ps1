# Registers the live investment-review tasks: a preparation step after each
# close digest, a one-minute poller through the review window, and the
# next-morning execution run for policy-approved intents.
# Run once, interactively, as the account that should own these tasks.
# Re-running replaces each task (Register-ScheduledTask -Force).
#
# Both tasks carry two weekday triggers. The 15:xx triggers only do real
# work on NYSE half-days; on a normal day prepare no-ops on the calendar
# and the poller finds nothing due. The 18:xx triggers correspondingly
# find nothing on half-days. The schedule revision in SQLite is the
# authority on due times; these triggers only make sure a worker is
# awake to look.

# Same interactive, highest-privilege principal as the digester installer;
# see the note there about Codex's sandbox runner.

param([switch]$Enable)

$RepoRoot = "C:\Users\Administrator\Documents\projects\boustrategy"
$PrepareScript = Join-Path $RepoRoot "ops\run-live-prepare.ps1"
$ExecuteScript = Join-Path $RepoRoot "ops\run-live-execution.ps1"
$PollerScript = Join-Path $RepoRoot "ops\run-review-poller.ps1"
$Weekdays = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

function Register-BouTask {
    param(
        [string]$Name,
        [string]$Arguments,
        [Microsoft.Management.Infrastructure.CimInstance[]]$Triggers,
        [int]$TimeLimitMinutes,
        [string]$Description
    )
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass $Arguments" `
        -WorkingDirectory $RepoRoot
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
        -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeLimitMinutes) -MultipleInstances IgnoreNew `
        -Disable:(-not $Enable)
    $Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Triggers `
        -Settings $Settings -Description $Description -Principal $Principal -Force | Out-Null
    Write-Output "Registered: $Name"
}

Register-BouTask -Name "boustrategy-review-prepare" `
    -Arguments "-File `"$PrepareScript`" -Window close" `
    -Triggers @((New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 18:10)) `
    -TimeLimitMinutes 20 `
    -Description "boustrategy live review: market preparation, broker snapshot and prepared live run after the close digest"

Register-BouTask -Name "boustrategy-review-prepare-halfday" `
    -Arguments "-File `"$PrepareScript`" -Window halfday" `
    -Triggers @((New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 15:10)) `
    -TimeLimitMinutes 20 `
    -Description "boustrategy live review: preparation on NYSE half-days"

$PollerTriggers = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 18:15),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 15:15)
)
foreach ($Trigger in $PollerTriggers) {
    $Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 00:00 `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Minutes 30)).Repetition
}
Register-BouTask -Name "boustrategy-review-poller" `
    -Arguments "-File `"$PollerScript`" -Schedule live-close" `
    -Triggers $PollerTriggers `
    -TimeLimitMinutes 60 `
    -Description "boustrategy live review: one-minute scheduler tick through the review window"

Register-BouTask -Name "boustrategy-live-execute" `
    -Arguments "-File `"$ExecuteScript`"" `
    -Triggers @(
        (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 09:35),
        (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 12:15)
    ) `
    -TimeLimitMinutes 50 `
    -Description "boustrategy live execution: place pending policy-approved intents during regular hours"

Write-Output "`nFour tasks registered. Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'boustrategy-review-*' | Select TaskName,State"
