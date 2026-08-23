param(
    [switch]$ApiKeyOnly,
    [switch]$IncludeOpenAI
)

$ErrorActionPreference = "Stop"

$secretDir = Join-Path $PSScriptRoot "data\secrets"
$apiFile = Join-Path $secretDir "calle_api_key.dpapi"
$phoneFile = Join-Path $secretDir "calle_phone.dpapi"
$openaiFile = Join-Path $secretDir "openai_api_key.dpapi"

if (-not (Test-Path $apiFile)) {
    throw "Encrypted CALL-E API key file not found."
}

if (-not $ApiKeyOnly -and -not (Test-Path $phoneFile)) {
    throw "Encrypted CALL-E phone file not found."
}

if ($IncludeOpenAI -and -not (Test-Path $openaiFile)) {
    throw "Encrypted OpenAI API key file not found. Run setup_openai_key.ps1 first."
}

$apiSecure = ConvertTo-SecureString (
    [System.IO.File]::ReadAllText($apiFile).Trim()
)

$env:CALLE_API_KEY = [System.Net.NetworkCredential]::new(
    "",
    $apiSecure
).Password

if ($ApiKeyOnly) {
    Remove-Item Env:CALLE_TEST_PHONE -ErrorAction SilentlyContinue
}
else {
    $phoneSecure = ConvertTo-SecureString (
        [System.IO.File]::ReadAllText($phoneFile).Trim()
    )

    $env:CALLE_TEST_PHONE = [System.Net.NetworkCredential]::new(
        "",
        $phoneSecure
    ).Password
}

if ($IncludeOpenAI) {
    $openaiSecure = ConvertTo-SecureString (
        [System.IO.File]::ReadAllText($openaiFile).Trim()
    )

    $env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new(
        "",
        $openaiSecure
    ).Password
}
else {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
}

Write-Host "DPAPI_LOAD=PASS"
Write-Host "API_KEY_LOADED=" ([bool]$env:CALLE_API_KEY)
Write-Host "PHONE_LOADED=" ([bool](-not $ApiKeyOnly -and $env:CALLE_TEST_PHONE))
Write-Host "OPENAI_KEY_LOADED=" ([bool]($IncludeOpenAI -and $env:OPENAI_API_KEY))
Write-Host "SECRET_VALUES_PRINTED=NO"
