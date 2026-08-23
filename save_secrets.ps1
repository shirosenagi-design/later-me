param(
    [switch]$IncludeOpenAI,
    [switch]$ApiKeyOnly,
    [switch]$OpenAIOnly,
    [switch]$Interactive,
    [string]$SecretRoot
)

$ErrorActionPreference = "Stop"

if ($OpenAIOnly -and ($ApiKeyOnly -or $IncludeOpenAI)) {
    throw "OpenAIOnly cannot be combined with ApiKeyOnly or IncludeOpenAI."
}

$secretDir = if ([string]::IsNullOrWhiteSpace($SecretRoot)) {
    Join-Path $PSScriptRoot "data\secrets"
}
else {
    [System.IO.Path]::GetFullPath($SecretRoot)
}

$apiFile = Join-Path $secretDir "calle_api_key.dpapi"
$phoneFile = Join-Path $secretDir "calle_phone.dpapi"
$openaiFile = Join-Path $secretDir "openai_api_key.dpapi"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-SecretInput {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentName,
        [Parameter(Mandatory = $true)][string]$Prompt
    )

    if ($Interactive) {
        $secure = Read-Host $Prompt -AsSecureString
    }
    else {
        $plain = [Environment]::GetEnvironmentVariable($EnvironmentName)
        if ([string]::IsNullOrWhiteSpace($plain)) {
            throw "$EnvironmentName is not loaded."
        }
        $secure = ConvertTo-SecureString $plain -AsPlainText -Force
        $plain = $null
    }

    $check = [System.Net.NetworkCredential]::new("", $secure).Password
    if ([string]::IsNullOrWhiteSpace($check)) {
        throw "$EnvironmentName was empty."
    }
    $check = $null
    return $secure
}

function Save-DpapiSecret {
    param(
        [Parameter(Mandatory = $true)][Security.SecureString]$SecureValue,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $encrypted = ConvertFrom-SecureString $SecureValue
    [System.IO.File]::WriteAllText($Destination, $encrypted, $utf8NoBom)

    $roundtripSecure = ConvertTo-SecureString (
        [System.IO.File]::ReadAllText($Destination).Trim()
    )
    $originalPlain = [System.Net.NetworkCredential]::new(
        "",
        $SecureValue
    ).Password
    $roundtripPlain = [System.Net.NetworkCredential]::new(
        "",
        $roundtripSecure
    ).Password
    $matches = $originalPlain -ceq $roundtripPlain
    $originalPlain = $null
    $roundtripPlain = $null
    $roundtripSecure = $null
    return $matches
}

$writeApi = -not $OpenAIOnly
$writePhone = -not $OpenAIOnly -and -not $ApiKeyOnly
$writeOpenAI = $OpenAIOnly -or $IncludeOpenAI

New-Item -ItemType Directory -Force -Path $secretDir | Out-Null

$apiRoundtrip = $null
$phoneRoundtrip = $null
$openaiRoundtrip = $null

if ($writeApi) {
    $apiSecure = Get-SecretInput `
        -EnvironmentName "CALLE_API_KEY" `
        -Prompt "Enter your CALL-E API key (input is hidden)"
    $apiRoundtrip = Save-DpapiSecret `
        -SecureValue $apiSecure `
        -Destination $apiFile
    $apiSecure = $null
}

if ($writePhone) {
    $phoneSecure = Get-SecretInput `
        -EnvironmentName "CALLE_TEST_PHONE" `
        -Prompt "Enter the legacy CALL-E test phone (input is hidden)"
    $phoneRoundtrip = Save-DpapiSecret `
        -SecureValue $phoneSecure `
        -Destination $phoneFile
    $phoneSecure = $null
}

if ($writeOpenAI) {
    $openaiSecure = Get-SecretInput `
        -EnvironmentName "OPENAI_API_KEY" `
        -Prompt "Enter your OpenAI API key (input is hidden)"
    $openaiRoundtrip = Save-DpapiSecret `
        -SecureValue $openaiSecure `
        -Destination $openaiFile
    $openaiSecure = $null
}

Write-Host "DPAPI_SAVE=PASS"
Write-Host "API_KEY_SAVED=" $writeApi
if ($writeApi) {
    Write-Host "API_KEY_ROUNDTRIP=" $apiRoundtrip
}
Write-Host "PHONE_SAVED=" $writePhone
if ($writePhone) {
    Write-Host "PHONE_ROUNDTRIP=" $phoneRoundtrip
}
Write-Host "OPENAI_KEY_SAVED=" $writeOpenAI
if ($writeOpenAI) {
    Write-Host "OPENAI_KEY_ROUNDTRIP=" $openaiRoundtrip
}
Write-Host "SECRET_VALUES_PRINTED=NO"
