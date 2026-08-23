$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$saver = Join-Path $PSScriptRoot "save_secrets.ps1"
if (-not (Test-Path -LiteralPath $saver -PathType Leaf)) {
    throw "save_secrets.ps1 not found."
}

Write-Host "=== Later, Me. Judge Credential Setup ==="
Write-Host "Use credentials from your own accounts."
Write-Host "Secret input is hidden and stored with Windows CurrentUser DPAPI."
Write-Host "No phone number is requested here; register your own number in onboarding."
Write-Host

& $saver -ApiKeyOnly -Interactive

Write-Host
$enableOpenAI = Read-Host (
    "Enable optional OpenAI post-call Relationship Trace? [y/N]"
)
$openaiSaved = $false
if ($enableOpenAI -match "^(?i:y|yes)$") {
    & $saver -OpenAIOnly -Interactive
    $openaiSaved = $true
}

Write-Host
Write-Host "JUDGE_SECRET_SETUP=PASS"
Write-Host "CALL_E_KEY_SAVED=YES"
Write-Host "OPENAI_KEY_SAVED=" $openaiSaved
Write-Host "PHONE_SAVED_BY_CREDENTIAL_SETUP=NO"
Write-Host "SECRET_VALUES_PRINTED=NO"
