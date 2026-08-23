param(
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$pythonDownload = "https://www.python.org/downloads/windows/"
$nodeDownload = "https://nodejs.org/en/download"
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$webRoot = Join-Path $PSScriptRoot "web"
$secretSetup = Join-Path $PSScriptRoot "judge_secret_setup.ps1"

function Get-Python313Command {
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $versionOutput = @(
            & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        )
        $version = if ($versionOutput.Count) {
            ([string]$versionOutput[-1]).Trim()
        }
        else {
            ""
        }
        if ($LASTEXITCODE -ne 0 -or $version -ne "3.13") {
            throw "The existing .venv is not CPython 3.13. Remove it manually and rerun setup."
        }
        return [pscustomobject]@{
            Executable = $venvPython
            Prefix = @()
            IsVenv = $true
        }
    }

    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $versionOutput = @(
            & $launcher.Source -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        )
        $version = if ($versionOutput.Count) {
            ([string]$versionOutput[-1]).Trim()
        }
        else {
            ""
        }
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.13") {
            return [pscustomobject]@{
                Executable = $launcher.Source
                Prefix = @("-3.13")
                IsVenv = $false
            }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $versionOutput = @(
            & $python.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        )
        $version = if ($versionOutput.Count) {
            ([string]$versionOutput[-1]).Trim()
        }
        else {
            ""
        }
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.13") {
            return [pscustomobject]@{
                Executable = $python.Source
                Prefix = @()
                IsVenv = $false
            }
        }
    }

    throw "CPython 3.13 is required. Install it from $pythonDownload, then rerun judge_setup.cmd."
}

function Assert-SupportedNode {
    $node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $node -or $null -eq $npm) {
        throw "Node.js and npm are required. Install a supported version from $nodeDownload."
    }

    $rawVersion = (& $node.Source --version).Trim().TrimStart("v")
    try {
        $version = [Version]::Parse($rawVersion)
    }
    catch {
        throw "The installed Node.js version could not be read."
    }

    $supported = (
        ($version.Major -eq 20 -and $version.Minor -ge 19) -or
        ($version.Major -eq 22 -and $version.Minor -ge 12) -or
        ($version.Major -gt 22)
    )
    if (-not $supported) {
        throw (
            "Node.js ^20.19.0 or >=22.12.0 is required. " +
            "Install it from $nodeDownload, then rerun judge_setup.cmd."
        )
    }

    return [pscustomobject]@{
        Node = $node.Source
        Npm = $npm.Source
        Version = $version.ToString()
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Later, Me. judge setup requires Windows 10 or 11."
}
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "requirements.txt not found."
}
if (-not (Test-Path -LiteralPath (Join-Path $webRoot "package-lock.json") -PathType Leaf)) {
    throw "web/package-lock.json not found."
}
if (-not (Test-Path -LiteralPath $secretSetup -PathType Leaf)) {
    throw "judge_secret_setup.ps1 not found."
}

$pythonCommand = Get-Python313Command
$nodeCommand = Assert-SupportedNode

if ($SelfTest) {
    Write-Host "JUDGE_SETUP_SELF_TEST=PASS"
    Write-Host "WINDOWS_REQUIRED=YES"
    Write-Host "PYTHON_3_13_AVAILABLE=YES"
    Write-Host "NODE_VERSION_SUPPORTED=YES"
    Write-Host "SYSTEM_INSTALL_PERFORMED=NO"
    Write-Host "CREDENTIAL_PROMPT_USED=NO"
    Write-Host "EXTERNAL_API_REQUEST_SENT=NO"
    Write-Host "REAL_CALL_SENT=NO"
    exit 0
}

Write-Host "=== Later, Me. Judge Setup ==="
Write-Host
Write-Host "IMPORTANT: This folder must already be in its final location."
Write-Host "Do not move it after scheduling a call; the Windows task stores this path."
$confirmed = Read-Host "Type YES to confirm this is the final location"
if ($confirmed -cne "YES") {
    throw "Setup stopped before making changes. Move the folder first, then rerun."
}

if (-not $pythonCommand.IsVenv) {
    Write-Host "Creating the repository-local CPython 3.13 environment..."
    $pythonExecutable = $pythonCommand.Executable
    $pythonPrefix = @($pythonCommand.Prefix)
    & $pythonExecutable @pythonPrefix -m venv ".venv"
    if ($LASTEXITCODE -ne 0) {
        throw "Python virtual environment creation failed."
    }
}

Write-Host "Installing pinned Python requirements..."
& $venvPython -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Python requirements installation failed."
}

Write-Host "Installing locked frontend dependencies..."
$npmExecutable = $nodeCommand.Npm
Push-Location $webRoot
try {
    & $npmExecutable ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed."
    }
    & $npmExecutable run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed."
    }
}
finally {
    Pop-Location
}

foreach ($directory in @("data", "results", "logs")) {
    New-Item -ItemType Directory -Force -Path (
        Join-Path $PSScriptRoot $directory
    ) | Out-Null
}

& $secretSetup

Write-Host
Write-Host "JUDGE_SETUP=PASS"
Write-Host "SYSTEM_INSTALL_PERFORMED=NO"
Write-Host "PRODUCTION_MINIMUM_HOURS=4"
Write-Host "DEV_SHORT_HORIZON_ENABLED=NO"
Write-Host "SECRET_VALUES_PRINTED=NO"
Write-Host "Next: run judge_start.cmd"
