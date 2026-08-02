$ErrorActionPreference = "Stop"
$lease = Join-Path (Get-Location) "state/research.lease"
if (Test-Path $lease) { Get-Content $lease } else { Write-Output '{"active":false}' }
