#requires -Version 5.1
<#
.SYNOPSIS
  Bounded read-only wrapper for scripts/ai/operator_context_snapshot.py

.DESCRIPTION
  Calls the Python authority and preserves its exit status. Prefer
  scripts/operators/marketos_ai_session.ps1 -Action snapshot for the
  documented AI-chat session entrypoint. This file stays a thin wrapper.
#>
[CmdletBinding()]
param(
    [switch] $IncludeFrontend,
    [switch] $NoGitHub,
    [double] $Timeout = 45,
    [string] $RepositoryPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($RepositoryPath) {
    if ($RepositoryPath -match '\.\.|[;&|<>`]|\$\(') {
        [Console]::Error.WriteLine("rejected unexpected RepositoryPath")
        exit 2
    }
    $repoRoot = (Resolve-Path -LiteralPath $RepositoryPath).Path
} else {
    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
$scriptPath = Join-Path $repoRoot "scripts\ai\operator_context_snapshot.py"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    [Console]::Error.WriteLine("unexpected repository path: missing operator_context_snapshot.py")
    exit 2
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    [Console]::Error.WriteLine("python interpreter unavailable")
    exit 2
}
$argv = @($scriptPath, "--json", "--timeout", "$Timeout", "--repository", $repoRoot)
if ($IncludeFrontend) { $argv += "--include-frontend" }
if ($NoGitHub) { $argv += "--no-github" }
& $python.Source @argv
exit $LASTEXITCODE
