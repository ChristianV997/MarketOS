#requires -Version 5.1
<#
.SYNOPSIS
  Bounded read-only wrapper for scripts/ai/operator_context_snapshot.py

.DESCRIPTION
  Calls the Python authority and preserves its exit status. Does not implement
  a second snapshot schema or quality-gate logic.
#>
[CmdletBinding()]
param(
    [switch] $IncludeFrontend,
    [switch] $NoGitHub,
    [double] $Timeout = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptPath = Join-Path $repoRoot "scripts\ai\operator_context_snapshot.py"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    [Console]::Error.WriteLine("python interpreter unavailable")
    exit 2
}
$argv = @($scriptPath, "--json", "--timeout", "$Timeout")
if ($IncludeFrontend) { $argv += "--include-frontend" }
if ($NoGitHub) { $argv += "--no-github" }
& $python.Source @argv
exit $LASTEXITCODE
