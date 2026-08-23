param(
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$backendUrl = "http://127.0.0.1:8787"
$frontendUrl = "http://127.0.0.1:5173/"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$backendScript = Join-Path $PSScriptRoot "web_api.py"
$webRoot = Join-Path $PSScriptRoot "web"
$callESecret = Join-Path $PSScriptRoot "data\secrets\calle_api_key.dpapi"
$logRoot = Join-Path $PSScriptRoot "logs"

function Test-LocalPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $pending.Wait(400)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-LaterMeHealth {
    try {
        return Invoke-RestMethod `
            -Uri "$backendUrl/api/health" `
            -Method Get `
            -TimeoutSec 2 `
            -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Test-LaterMeFrontend {
    try {
        $response = Invoke-WebRequest `
            -Uri $frontendUrl `
            -UseBasicParsing `
            -TimeoutSec 2 `
            -ErrorAction Stop
        return $response.StatusCode -eq 200 -and $response.Content -match "Later, Me\."
    }
    catch {
        return $false
    }
}

if ($SelfTest) {
    Write-Host "JUDGE_START_SELF_TEST=PASS"
    Write-Host "CALL_E_STORAGE_MODE=real"
    Write-Host "CALL_E_DELIVERY_MODE=live"
    Write-Host "CALL_E_DEV_SHORT_HORIZON=0"
    Write-Host "PRODUCTION_MINIMUM_HOURS=4"
    Write-Host "OPENAI_REQUIRED=NO"
    Write-Host "SECRET_LOADED_BY_LAUNCHER=NO"
    Write-Host "TASK_REGISTERED_BY_LAUNCHER=NO"
    Write-Host "EXTERNAL_API_REQUEST_SENT=NO"
    Write-Host "REAL_CALL_SENT=NO"
    exit 0
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Setup is incomplete: .venv CPython was not found. Run judge_setup.cmd."
}
if (-not (Test-Path -LiteralPath $backendScript -PathType Leaf)) {
    throw "web_api.py not found."
}
if (-not (Test-Path -LiteralPath (Join-Path $webRoot "node_modules") -PathType Container)) {
    throw "Frontend dependencies were not found. Run judge_setup.cmd."
}
if (-not (Test-Path -LiteralPath $callESecret -PathType Leaf)) {
    throw "Your protected CALL-E credential was not found. Run judge_setup.cmd."
}

$npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($null -eq $npm) {
    throw "npm was not found. Run judge_setup.cmd after installing supported Node.js."
}

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$env:CALL_E_STORAGE_MODE = "real"
$env:CALL_E_DELIVERY_MODE = "live"
$env:CALL_E_DEV_SHORT_HORIZON = "0"
Remove-Item Env:CALL_E_DATA_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:CALL_E_RESULTS_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:CALL_E_INSTANCE_ID -ErrorAction SilentlyContinue

$health = Get-LaterMeHealth
if ($null -eq $health) {
    if (Test-LocalPort -Port 8787) {
        throw "Port 8787 is already used by an unrecognized process. Stop it manually."
    }
    Start-Process `
        -FilePath $venvPython `
        -ArgumentList @($backendScript) `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "judge_backend_stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "judge_backend_stderr.log")

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 250
        $health = Get-LaterMeHealth
        if ($null -ne $health) {
            break
        }
    }
}

if ($null -eq $health) {
    throw "Later, Me. backend did not become ready. Check logs/judge_backend_stderr.log."
}
if (
    $health.storage_mode -ne "real" -or
    $health.delivery_mode -ne "live" -or
    $health.dev_short_horizon_enabled -ne $false -or
    [int]$health.booking_minimum_minutes -ne 240
) {
    throw "The backend is running with an unexpected or unsafe configuration."
}

if (-not (Test-LaterMeFrontend)) {
    if (Test-LocalPort -Port 5173) {
        throw "Port 5173 is already used by an unrecognized process. Stop it manually."
    }

    $env:VITE_API_TARGET = $backendUrl
    Remove-Item Env:VITE_CALL_E_QA_INSTANCE_ID -ErrorAction SilentlyContinue
    Start-Process `
        -FilePath $npm.Source `
        -ArgumentList @(
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort"
        ) `
        -WorkingDirectory $webRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "judge_frontend_stdout.log") `
        -RedirectStandardError (Join-Path $logRoot "judge_frontend_stderr.log")

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-LaterMeFrontend) {
            break
        }
    }
}

if (-not (Test-LaterMeFrontend)) {
    throw "Later, Me. frontend did not become ready. Check logs/judge_frontend_stderr.log."
}

Write-Host "JUDGE_START=PASS"
Write-Host "BACKEND_URL=$backendUrl"
Write-Host "FRONTEND_URL=$frontendUrl"
Write-Host "PRODUCTION_MINIMUM_HOURS=4"
Write-Host "DEV_SHORT_HORIZON_ENABLED=NO"
Write-Host "SECRET_VALUES_PRINTED=NO"
Write-Host "No call is placed until you create a reservation in the UI."

Start-Process $frontendUrl
