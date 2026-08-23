param(
    [switch]$Arm,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$taskName = "CALL-E-Hackathon-LiveCall"
$pendingFile = Join-Path $PSScriptRoot "data\pending_call.json"
$runner = Join-Path $PSScriptRoot "run_dispatch.ps1"

function Remove-ExistingLiveTask {
    $existingTask = Get-ScheduledTask `
        -TaskPath "\" `
        -ErrorAction Stop |
        Where-Object { $_.TaskName -eq $taskName }

    if ($null -ne $existingTask) {
        Unregister-ScheduledTask `
            -TaskName $taskName `
            -TaskPath "\" `
            -Confirm:$false `
            -ErrorAction Stop
    }
}

if ($Remove) {
    Write-Host "=== LIVE TASK REMOVAL PREVIEW ==="
    Write-Host "TASK_NAME=$taskName"

    if (-not $Arm) {
        Write-Host "TASK_REMOVE=PREVIEW"
        Write-Host "TASK_SCHEDULER_CHANGED=NO"
        exit 0
    }

    Remove-ExistingLiveTask

    Write-Host "TASK_REMOVE=PASS"
    Write-Host "TASK_SCHEDULER_CHANGED=YES"
    exit 0
}

if (-not (Test-Path $pendingFile)) {
    throw "pending_call.json not found."
}

if (-not (Test-Path $runner)) {
    throw "run_dispatch.ps1 not found."
}

$record = Get-Content $pendingFile -Raw -Encoding UTF8 |
    ConvertFrom-Json

if ($record.status -ne "pending_local") {
    throw "Pending call status is not pending_local."
}

$attemptCount = 0

if ($null -ne $record.dispatch_attempt_count) {
    $attemptCount = [int]$record.dispatch_attempt_count
}

if ($attemptCount -ge 1) {
    throw "Pending call already has a dispatch attempt."
}

$scheduled = [DateTimeOffset]::Parse(
    $record.scheduled_for
)

$now = [DateTimeOffset]::Now

if ($scheduled -le $now) {
    throw "Scheduled time is not in the future."
}

Write-Host "=== LIVE TASK PREVIEW ==="
Write-Host "TASK_NAME=$taskName"
Write-Host "SCHEDULED_FOR=$($scheduled.ToString('o'))"
Write-Host "RUNNER=$runner"
Write-Host "ACTION=run_dispatch.ps1 -ExecuteCall -EnableRelationshipTrace"

if (-not $Arm) {
    Write-Host "ARMED=NO"
    Write-Host "REAL_CALL_SCHEDULED=NO"
    exit 0
}

Write-Host "TASK_STAGE=REMOVE_EXISTING"
Remove-ExistingLiveTask

Write-Host "TASK_STAGE=BUILD_DEFINITION"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -ExecuteCall -EnableRelationshipTrace"

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At $scheduled.LocalDateTime

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Write-Host "TASK_STAGE=REGISTER"
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "One-shot CALL-E future-self call." `
    | Out-Null

Write-Host "TASK_STAGE=CONFIRMED"
Write-Host "TASK_REGISTER=PASS"
Write-Host "ARMED=YES"
Write-Host "REAL_CALL_SCHEDULED=YES"
