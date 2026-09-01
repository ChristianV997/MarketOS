# Offline contract validation for the Cursor Cloud Agent environment.
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$lockfile = Join-Path $repoRoot "frontend\package-lock.json"
if (-not (Test-Path $lockfile)) {
  throw "frontend/package-lock.json is required for reproducible setup"
}

foreach ($shellScript in @("install.sh", "validate.sh")) {
  $scriptPath = Join-Path $repoRoot ".cursor\$shellScript"
  $scriptText = Get-Content $scriptPath -Raw -Encoding utf8
  if ($scriptText -match "`r") {
    throw "$shellScript contains CRLF line endings; run 'git add --renormalize .cursor' or use LF checkout policy"
  }
}

& node --test (Join-Path $repoRoot ".cursor\environment.contract.test.mjs")

Write-Output "cursor environment contract ok"
