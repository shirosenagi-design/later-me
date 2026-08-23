param(
    [switch]$ExecuteCall,
    [switch]$EnableRelationshipTrace
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$dispatcherPath = Join-Path $PSScriptRoot "dispatch_call.py"
$postProcessorPath = Join-Path $PSScriptRoot "relationship_trace_postprocess.py"
$secretLoader = Join-Path $PSScriptRoot "load_secrets.ps1"
$logDir = Join-Path $PSScriptRoot "logs"

if (-not (Test-Path $pythonPath)) { throw "Venv Python not found." }
if (-not (Test-Path $dispatcherPath)) { throw "dispatch_call.py not found." }
if (-not (Test-Path $secretLoader)) { throw "load_secrets.ps1 not found." }

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Phase 1 credentials: CALL-E only.
. $secretLoader -ApiKeyOnly
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CALL_E_RELATIONSHIP_TRACE_ENABLED -ErrorAction SilentlyContinue

$runnerStarted = [DateTimeOffset]::Now
$runnerStartedIso = $runnerStarted.ToString("o")
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "dispatch_$timestamp.log"

$argsList = @($dispatcherPath)

if ($ExecuteCall) {
    $argsList += "--execute-call"
    $mode = "LIVE"
}
else {
    $mode = "DRY_RUN"
}

"RUNNER_START=$runnerStartedIso" | Add-Content $logFile
"MODE=$mode" | Add-Content $logFile
"RELATIONSHIP_TRACE_POSTPROCESS_REQUESTED=$([bool]$EnableRelationshipTrace)" |
    Add-Content $logFile

Write-Host "=== CALL-E WINDOWS RUNNER ==="
Write-Host "MODE=$mode"
Write-Host "RELATIONSHIP_TRACE_POSTPROCESS_REQUESTED=$([bool]$EnableRelationshipTrace)"

# Phase 1: the real CALL-E phone process.
# No OpenAI credential is loaded and dispatch_call.py has no trace dependency.
& $pythonPath @argsList 2>&1 |
    Tee-Object -FilePath $logFile -Append

$dispatchExitCode = $LASTEXITCODE
"DISPATCH_EXIT_CODE=$dispatchExitCode" | Add-Content $logFile

# Phase 2: optional, independent, best-effort post-call inference.
if ($EnableRelationshipTrace) {
    Write-Host
    Write-Host "=== RELATIONSHIP TRACE POSTPROCESS ==="

    try {
        if (-not (Test-Path $postProcessorPath)) {
            throw "relationship_trace_postprocess.py not found."
        }

        # OpenAI key is loaded only after dispatch_call.py has returned.
        . $secretLoader -ApiKeyOnly -IncludeOpenAI

        & $pythonPath $postProcessorPath --since $runnerStartedIso 2>&1 |
            Tee-Object -FilePath $logFile -Append

        $traceExitCode = $LASTEXITCODE
        "RELATIONSHIP_TRACE_POSTPROCESS_EXIT_CODE=$traceExitCode" |
            Add-Content $logFile

        if ($traceExitCode -ne 0) {
            Write-Host "RELATIONSHIP_TRACE_POSTPROCESS=FAILED_BUT_CALL_RESULT_PRESERVED"
        }
    }
    catch {
        "RELATIONSHIP_TRACE_POSTPROCESS_EXCEPTION=$($_.Exception.GetType().Name)" |
            Add-Content $logFile
        Write-Host "RELATIONSHIP_TRACE_POSTPROCESS=FAILED_BUT_CALL_RESULT_PRESERVED"
        Write-Host "FAILURE_TYPE=$($_.Exception.GetType().Name)"
    }
    finally {
        Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    }
}

Remove-Item Env:CALLE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CALL_E_RELATIONSHIP_TRACE_ENABLED -ErrorAction SilentlyContinue

Write-Host
Write-Host "DISPATCH_EXIT_CODE=$dispatchExitCode"
Write-Host "LOG_FILE=$logFile"

# Phone dispatch result stays authoritative even if the optional postprocess fails.
exit $dispatchExitCode
