param(
    [string]$RepositoryRoot = $PSScriptRoot,
    [string]$Commitish = "HEAD",
    [string]$OutputPath,
    [switch]$ManifestOnly
)

$ErrorActionPreference = "Stop"

$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$git = Get-Command "git.exe" -ErrorAction SilentlyContinue
if ($null -eq $git) {
    throw "Git is required to build the tracked-only judge package."
}

$commit = (& $git.Source -C $repository rev-parse --verify "$Commitish^{commit}" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
    throw "The requested committed snapshot was not found."
}

$files = @(& $git.Source -C $repository ls-tree -r --name-only $commit)
if ($LASTEXITCODE -ne 0 -or $files.Count -eq 0) {
    throw "The committed package manifest could not be read."
}

$requiredFiles = @(
    ".gitignore",
    "README.md",
    "LICENSE",
    "COMMERCIAL_USE.md",
    "ART_PROVENANCE.md",
    "JUDGE_QUICKSTART.md",
    "judge_setup.cmd",
    "judge_setup.ps1",
    "judge_secret_setup.ps1",
    "judge_start.cmd",
    "judge_start.ps1",
    "build_judge_package.ps1",
    "requirements.txt",
    "save_secrets.ps1",
    "load_secrets.ps1",
    "web_api.py",
    "dispatch_call.py",
    "run_dispatch.ps1",
    "register_live_task.ps1",
    "web/package.json",
    "web/package-lock.json",
    "web/src/main.tsx"
)

$missing = @($requiredFiles | Where-Object { $_ -notin $files })
if ($missing.Count -gt 0) {
    throw "Committed judge package files are missing: $($missing -join ', ')"
}

$forbiddenPatterns = @(
    "(^|/)(?:\.git|\.venv|node_modules|dist|data|results|logs|diagnostics)(/|$)",
    "(?i)(?:^|/)(?:pending_call\.json|completed_calls\.jsonl)$",
    "(?i)\.dpapi$",
    "(?i)(?:^|/)\.env(?:\.|$)",
    "(?i)\.zip$"
)
$forbidden = @(
    $files | Where-Object {
        $candidate = $_
        [bool]($forbiddenPatterns | Where-Object { $candidate -match $_ })
    }
)
if ($forbidden.Count -gt 0) {
    throw "Private or generated paths were found in the committed manifest."
}

Write-Host "JUDGE_PACKAGE_MANIFEST=PASS"
Write-Host "SOURCE=COMMITTED_GIT_TREE"
Write-Host "COMMIT=$commit"
Write-Host "FILE_COUNT=$($files.Count)"
foreach ($file in $files) {
    Write-Host "PACKAGE_FILE=$file"
}

if ($ManifestOnly) {
    Write-Host "PACKAGE_CREATED=NO"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $shortCommit = $commit.Substring(0, 12)
    $OutputPath = Join-Path $repository "release\later-me-judge-$shortCommit.zip"
}
$destination = [System.IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $destination) {
    throw "Output already exists; refusing to overwrite it."
}
$parent = Split-Path -Parent $destination
New-Item -ItemType Directory -Force -Path $parent | Out-Null

& $git.Source -C $repository archive `
    --format=zip `
    --output=$destination `
    $commit
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $destination)) {
    throw "Judge package creation failed."
}

Write-Host "PACKAGE_CREATED=YES"
Write-Host "OUTPUT_BASENAME=$([System.IO.Path]::GetFileName($destination))"
Write-Host "SECRET_VALUES_PRINTED=NO"
