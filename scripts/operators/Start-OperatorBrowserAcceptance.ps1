# Operator browser acceptance on Windows
# Fixture and local-UI evidence only. Does not start providers or claim live validation.
param(
  [string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
  [string]$Browser = "chrome",
  [string]$LiveUi = "",
  [string]$ArtifactDir = (Join-Path $env:TEMP "marketos-operator-browser-acceptance")
)
$ErrorActionPreference = "Stop"
$python = $env:PYTHON
if (-not $python) { $python = "python" }
$runner = Join-Path $Repo "scripts\ai\run_operator_browser_acceptance.py"
$runnerArgs = @($runner, "--browser", $Browser, "--json", "--artifact-dir", $ArtifactDir)
if ($LiveUi) { $runnerArgs += @("--live-ui", $LiveUi) }
& $python @runnerArgs
exit $LASTEXITCODE
