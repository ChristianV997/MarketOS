#requires -Version 5.1
<#
.SYNOPSIS
  Private staging acceptance (default: no network). Prints the probe contract.

.DESCRIPTION
  Does not treat Netlify preview as backend evidence. HTTP probes stay not_run
  until an operator-approved private URL is wired through a future allow-network policy.
#>
[CmdletBinding()]
param(
    [string] $PythonPath
)

& (Join-Path $PSScriptRoot "Invoke-MarketOSOperator.ps1") -Command staging-acceptance -PythonPath $PythonPath
exit $LASTEXITCODE
