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
$PollerScript = Join-Path $RepoRoot "ops\run-review-poller.ps1"
$ExecuteScript = Join-Path $RepoRoot "ops\run-live-execution.ps1"
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

function New-PollingTrigger {
    param([string]$At, [int]$Minutes = 30)
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At $At
    $Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 00:00 `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Minutes $Minutes)).Repetition
    return $Trigger
}

# The single-review layout used three differently named tasks. Leaving them behind
# would orphan triggers pointing at a wrapper whose parameters have changed.
$Retired = @(
    "boustrategy-review-prepare",
    "boustrategy-review-prepare-halfday",
    "boustrategy-review-poller"
)
foreach ($Name in $Retired) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Output "Removed retired task: $Name"
    }
}

# Preparation runs 15 minutes before each review's due time. The close task carries
# both the regular and the half-day trigger; the wrapper drops whichever is wrong.
Register-BouTask -Name "boustrategy-review-prepare-midday" `
    -Arguments "-File `"$PrepareScript`" -Slot midday" `
    -Triggers @((New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 12:45)) `
    -TimeLimitMinutes 20 `
    -Description "boustrategy live review: midday preparation and broker snapshot"

Register-BouTask -Name "boustrategy-review-prepare-preclose" `
    -Arguments "-File `"$PrepareScript`" -Slot preclose" `
    -Triggers @((New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 14:45)) `
    -TimeLimitMinutes 20 `
    -Description "boustrategy live review: pre-close preparation and broker snapshot"

Register-BouTask -Name "boustrategy-review-prepare-close" `
    -Arguments "-File `"$PrepareScript`" -Slot close" `
    -Triggers @(
        (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 18:10),
        (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 15:10)
    ) `
    -TimeLimitMinutes 20 `
    -Description "boustrategy live review: after-hours preparation and broker snapshot"

Register-BouTask -Name "boustrategy-review-poller-midday" `
    -Arguments "-File `"$PollerScript`" -Schedule live-midday" `
    -Triggers @((New-PollingTrigger -At 13:00)) `
    -TimeLimitMinutes 45 `
    -Description "boustrategy live review: midday scheduler tick"

Register-BouTask -Name "boustrategy-review-poller-preclose" `
    -Arguments "-File `"$PollerScript`" -Schedule live-preclose" `
    -Triggers @((New-PollingTrigger -At 15:00)) `
    -TimeLimitMinutes 45 `
    -Description "boustrategy live review: pre-close scheduler tick"

Register-BouTask -Name "boustrategy-review-poller-close" `
    -Arguments "-File `"$PollerScript`" -Schedule live-close" `
    -Triggers @((New-PollingTrigger -At 18:15), (New-PollingTrigger -At 15:15)) `
    -TimeLimitMinutes 45 `
    -Description "boustrategy live review: after-hours scheduler tick"

# Execution ticks through regular hours. A tick with nothing pending starts no model
# session, so the cadence costs a Python process and nothing else.
$ExecuteTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At 09:45
$ExecuteTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At 00:00 `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Hours 6)).Repetition
Register-BouTask -Name "boustrategy-live-execute" `
    -Arguments "-File `"$ExecuteScript`"" `
    -Triggers @($ExecuteTrigger) `
    -TimeLimitMinutes 14 `
    -Description "boustrategy live execution: place pending approved intents during regular hours"

Write-Output "`nSeven tasks registered. Verify with:"
Write-Output "  Get-ScheduledTask -TaskName 'boustrategy-review-*','boustrategy-live-*' | Select TaskName,State"
