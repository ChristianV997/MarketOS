#requires -Version 5.1
<#
.SYNOPSIS
  Windows-native MarketOS operator command surface (dry-run by default).

.DESCRIPTION
  Thin PowerShell wrapper around scripts/operators/windows_operator_workflow.py.
  Does not replace PR #228 (first-phase intelligence runner) or PR #230 (cockpit).
  Live/network/start flags are rejected. Paths with spaces are quoted via -LiteralPath.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/Invoke-MarketOSOperator.ps1 -Command preflight

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/Invoke-MarketOSOperator.ps1 -Command scenario-pack -OutputDirectory "$env:TEMP\marketos-operator-safe"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "preflight",
        "fixture-import",
        "supplier-import",
        "product-validation",
        "commerce-cycle",
        "batch-manifest",
        "client-safe-export",
        "phase-readiness",
        "inspect-evidence",
        "replay",
        "start-local",
        "staging-acceptance",
        "scenario-pack",
        "coderos-probe"
    )]
    [string] $Command,

    [string] $Source,
    [string] $Fixture,
    [string] $Manifest,
    [string] $Packet,
    [string] $Path,
    [string] $PackDir,
    [string] $ClientName,
    [string] $BaseUrl,
    [string] $OutputDirectory,
    [string] $PythonPath,
    [switch] $AllowNetwork,
    [switch] $AllowPublicNetwork,
    [switch] $WriteSupabase,
    [switch] $UseLiveProvider,
    [switch] $UseModelInference,
    [switch] $ClaimLiveExecution,
    [switch] $LiveValidated,
    [switch] $AllowStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$Workflow = Join-Path $RepoRoot "scripts\operators\windows_operator_workflow.py"

if ($AllowNetwork -or $AllowPublicNetwork -or $WriteSupabase -or $UseLiveProvider -or $UseModelInference -or $ClaimLiveExecution -or $LiveValidated -or $AllowStart) {
    Write-Error "blocked live/network/provider/start flag"
    exit 4
}

if (-not (Test-Path -LiteralPath $Workflow)) {
    Write-Error "missing workflow script: $Workflow"
    exit 2
}

function Resolve-Python {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            Write-Error "python interpreter not found: $PythonPath"
            exit 3
        }
        return @{ Command = $PythonPath; Prefix = @() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Command = $python.Source; Prefix = @() } }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Command = $py.Source; Prefix = @("-3.12") } }
    Write-Error "no supported python interpreter found (python or py -3.12)"
    exit 3
}

$Python = Resolve-Python
$invoke = New-Object System.Collections.Generic.List[string]
foreach ($item in $Python.Prefix) { $invoke.Add($item) }
$invoke.Add($Workflow)
$invoke.Add($Command)
$invoke.Add("--json")

function Add-Optional {
    param([string] $Flag, [string] $Value)
    if ($Value) {
        $invoke.Add($Flag)
        $invoke.Add($Value)
    }
}

Add-Optional "--source" $Source
Add-Optional "--fixture" $Fixture
Add-Optional "--manifest" $Manifest
Add-Optional "--packet" $Packet
Add-Optional "--path" $Path
Add-Optional "--pack-dir" $PackDir
Add-Optional "--client-name" $ClientName
Add-Optional "--base-url" $BaseUrl
Add-Optional "--output" $OutputDirectory

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $Python.Command @($invoke.ToArray())
    $code = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }
}
finally {
    $ErrorActionPreference = $previous
}
exit $code
