# Idempotent Windows bootstrap for MarketOS contributors.
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Invoke-MarketOsPython {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    & $python.Source @Args
    return
  }

  $python3 = Get-Command python3 -ErrorAction SilentlyContinue
  if ($python3) {
    & $python3.Source @Args
    return
  }

  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    & $pyLauncher.Source -3 @Args
    return
  }

  Write-Error "python is unavailable in this environment; install Python with venv/ensurepip enabled"
}

Invoke-MarketOsPython -c "import ensurepip" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Error "ensurepip is unavailable; install Python with the venv/ensurepip module enabled"
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Invoke-MarketOsPython -m venv .venv
}

& $venvPython -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dev.txt

$lockfile = Join-Path $repoRoot "frontend\package-lock.json"
if (-not (Test-Path $lockfile)) {
  Write-Error "frontend/package-lock.json is required for reproducible setup"
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
  $npm = Get-Command npm -ErrorAction Stop
}
& $npm.Source --prefix frontend ci --ignore-scripts --no-audit --no-fund

& (Join-Path $PSScriptRoot "validate.ps1")

Write-Output "MarketOS environment ready."
