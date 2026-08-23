param(
    [switch]$IncludeOpenAI
)

$ErrorActionPreference = "Stop"

$secretDir = Join-Path $PSScriptRoot "data\secrets"
$apiFile = Join-Path $secretDir "calle_api_key.dpapi"
$phoneFile = Join-Path $secretDir "calle_phone.dpapi"
$openaiFile = Join-Path $secretDir "openai_api_key.dpapi"

if ([string]::IsNullOrWhiteSpace($env:CALLE_API_KEY)) {
    throw "CALLE_API_KEY is not loaded."
}

if ([string]::IsNullOrWhiteSpace($env:CALLE_TEST_PHONE)) {
    throw "CALLE_TEST_PHONE is not loaded."
}

New-Item -ItemType Directory -Force -Path $secretDir | Out-Null

$apiSecure = ConvertTo-SecureString `
    $env:CALLE_API_KEY `
    -AsPlainText `
    -Force

$phoneSecure = ConvertTo-SecureString `
    $env:CALLE_TEST_PHONE `
    -AsPlainText `
    -Force

$apiEncrypted = ConvertFrom-SecureString $apiSecure
$phoneEncrypted = ConvertFrom-SecureString $phoneSecure

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

[System.IO.File]::WriteAllText(
    $apiFile,
    $apiEncrypted,
    $utf8NoBom
)

[System.IO.File]::WriteAllText(
    $phoneFile,
    $phoneEncrypted,
    $utf8NoBom
)

$apiCheck = ConvertTo-SecureString (
    [System.IO.File]::ReadAllText($apiFile).Trim()
)

$phoneCheck = ConvertTo-SecureString (
    [System.IO.File]::ReadAllText($phoneFile).Trim()
)

$apiPlain = [System.Net.NetworkCredential]::new(
    "",
    $apiCheck
).Password

$phonePlain = [System.Net.NetworkCredential]::new(
    "",
    $phoneCheck
).Password

Write-Host "DPAPI_SAVE=PASS"
Write-Host "API_KEY_ROUNDTRIP=" ($apiPlain -eq $env:CALLE_API_KEY)
Write-Host "PHONE_ROUNDTRIP=" ($phonePlain -eq $env:CALLE_TEST_PHONE)

if ($IncludeOpenAI) {
    $openaiSecure = $null

    if (-not [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        $openaiSecure = ConvertTo-SecureString `
            $env:OPENAI_API_KEY `
            -AsPlainText `
            -Force
    }
    else {
        $openaiSecure = Read-Host `
            "Enter OPENAI_API_KEY (input is hidden)" `
            -AsSecureString
    }

    $openaiPlainCheck = [System.Net.NetworkCredential]::new(
        "",
        $openaiSecure
    ).Password

    if ([string]::IsNullOrWhiteSpace($openaiPlainCheck)) {
        throw "OPENAI_API_KEY was empty."
    }

    $openaiEncrypted = ConvertFrom-SecureString $openaiSecure

    [System.IO.File]::WriteAllText(
        $openaiFile,
        $openaiEncrypted,
        $utf8NoBom
    )

    $openaiRoundtripSecure = ConvertTo-SecureString (
        [System.IO.File]::ReadAllText($openaiFile).Trim()
    )

    $openaiRoundtripPlain = [System.Net.NetworkCredential]::new(
        "",
        $openaiRoundtripSecure
    ).Password

    Write-Host "OPENAI_KEY_ROUNDTRIP=" ($openaiRoundtripPlain -eq $openaiPlainCheck)

    $openaiPlainCheck = $null
    $openaiRoundtripPlain = $null
    $openaiSecure = $null
    $openaiRoundtripSecure = $null
}

Write-Host "SECRET_VALUES_PRINTED=NO"
