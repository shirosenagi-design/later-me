$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$loader = Join-Path $PSScriptRoot "load_secrets.ps1"
$saver = Join-Path $PSScriptRoot "save_secrets.ps1"

if (-not (Test-Path $loader)) {
    throw "load_secrets.ps1 not found."
}

if (-not (Test-Path $saver)) {
    throw "save_secrets.ps1 not found."
}

Write-Host "=== CALL-E OpenAI Key Setup ==="
Write-Host "The key will be entered with hidden input and saved with Windows DPAPI."
Write-Host "The secret value will not be printed."
Write-Host

. $loader
& $saver -IncludeOpenAI

Remove-Item Env:CALLE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CALLE_TEST_PHONE -ErrorAction SilentlyContinue
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

Write-Host
Write-Host "OPENAI_DPAPI_SETUP=PASS"
Write-Host "You can close this window."
