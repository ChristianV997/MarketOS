# Idempotent Windows bootstrap for MarketOS contributors.
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

python -c "import ensurepip" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Error "ensurepip is unavailable; install Python with the venv/ensurepip module enabled"
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  python -m venv .venv
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

Write-Output "MarketOS environment ready."
