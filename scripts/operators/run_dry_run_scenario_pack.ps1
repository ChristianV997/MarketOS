#requires -Version 5.1
<#
.SYNOPSIS
  Complete dry-run scenario pack for Product Validation / Unit Economics sprints.
#>
[CmdletBinding()]
param(
    [string] $OutputDirectory = "$env:TEMP\marketos-operator-scenarios",
    [string] $PythonPath
)

$here = $PSScriptRoot
& (Join-Path $here "Invoke-MarketOSOperator.ps1") `
    -Command scenario-pack `
    -PackDir "tests/fixtures/windows_operator/scenarios" `
    -OutputDirectory $OutputDirectory `
    -PythonPath $PythonPath
exit $LASTEXITCODE
