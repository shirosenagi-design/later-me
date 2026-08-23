$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$taskName = "CALL-E-Hackathon-LiveCall"
$pendingFile = Join-Path $PSScriptRoot "data\pending_call.json"

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
$record = Get-Content $pendingFile -Raw -Encoding UTF8 | ConvertFrom-Json

$attemptCount = 0
if ($null -ne $record.dispatch_attempt_count) {
    $attemptCount = [int]$record.dispatch_attempt_count
}

$actionArgs = $task.Actions[0].Arguments
$triggerTime = [DateTimeOffset]::Parse(
    $task.Triggers[0].StartBoundary
)
$pendingTime = [DateTimeOffset]::Parse(
    $record.scheduled_for
)

$pass = $true

Write-Host "=== LIVE CALL PREFLIGHT ==="
Write-Host "TASK_EXISTS=YES"
Write-Host "NEXT_RUN_TIME=$($info.NextRunTime)"
Write-Host "PENDING_FOR=$($record.scheduled_for)"
Write-Host "PENDING_STATUS=$($record.status)"
Write-Host "DISPATCH_ATTEMPT_COUNT=$attemptCount"
Write-Host "WAKE_TO_RUN=$($task.Settings.WakeToRun)"
Write-Host "START_WHEN_AVAILABLE=$($task.Settings.StartWhenAvailable)"
Write-Host "EXECUTE_CALL_PRESENT=$($actionArgs -match '-ExecuteCall')"

if ($record.status -ne "pending_local") {
    $pass = $false
}

if ($attemptCount -ne 0) {
    $pass = $false
}

if ($actionArgs -notmatch "-ExecuteCall") {
    $pass = $false
}

if (
    $triggerTime.ToUnixTimeSeconds() -ne
    $pendingTime.ToUnixTimeSeconds()
) {
    $pass = $false
}

if ($task.Settings.WakeToRun -ne $true) {
    $pass = $false
}

Write-Host

if ($pass) {
    Write-Host "LIVE_PREFLIGHT=PASS"
    Write-Host "REAL_CALL_NOW=NO"
    Write-Host "WAITING_FOR_SCHEDULED_TIME=YES"
}
else {
    Write-Host "LIVE_PREFLIGHT=FAIL"
}
