$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$saver = Join-Path $PSScriptRoot "save_secrets.ps1"

if (-not (Test-Path $saver)) {
    throw "save_secrets.ps1 not found."
}

Write-Host "=== CALL-E OpenAI Key Setup ==="
Write-Host "The key will be entered with hidden input and saved with Windows DPAPI."
Write-Host "The secret value will not be printed."
Write-Host

& $saver -OpenAIOnly -Interactive

Write-Host
Write-Host "OPENAI_DPAPI_SETUP=PASS"
Write-Host "You can close this window."
