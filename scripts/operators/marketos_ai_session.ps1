#requires -Version 5.1
<#
.SYNOPSIS
  Bounded MarketOS AI-chat session entrypoint for Windows PowerShell.

.DESCRIPTION
  One documented operator surface for inspect / continue / validate work.
  It does not implement a second quality gate, API client, event system,
  cockpit, or deployment engine. It never stages or deletes files.

  Authorities reused, not copied:
    snapshot        -> scripts/ai/operator_context_snapshot.py (MarketOS.AIContext.v1)
    readiness       -> scripts/phase1_readiness_report.py + scripts/ai/check_dev_stack.py
    select-tests    -> scripts/ai/select_tests.py
    frontend-check  -> frontend npm scripts (PR #213 authority; default not_run in snapshot)
    backend-check   -> focused pytest/compileall/ruff for this lane
    final-check     -> run_local_quality_gate.py (no --execute) + pr_readiness + session_finish --dry-run + git diff --check

  PR #246 Invoke-MarketOSOperator.ps1 remains the Product Validation sprint
  authority. Do not merge these command sets.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/marketos_ai_session.ps1 -Action snapshot -NoGitHub

.EXAMPLE
  pwsh -NoProfile -File scripts/operators/marketos_ai_session.ps1 -Action select-tests
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "snapshot",
        "readiness",
        "select-tests",
        "frontend-check",
        "backend-check",
        "final-check"
    )]
    [string] $Action,

    [string] $RepositoryPath,
    [string] $PythonPath,
    [switch] $NoGitHub,
    [switch] $IncludeFrontend,
    [double] $Timeout = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Classification {
    param(
        [string] $Name,
        [string] $Class,
        [object] $Code
    )
    $line = "MARKETOS_CLASSIFICATION action=$Action check=$Name class=$Class exit=$Code"
    [Console]::Error.WriteLine($line)
}

function Stop-Session {
    param(
        [string] $Message,
        [int] $Code = 2,
        [string] $Class = "blocked"
    )
    Write-Classification -Name "session" -Class $Class -Code $Code
    [Console]::Error.WriteLine($Message)
    exit $Code
}

function Assert-SafePathText {
    param([string] $Value, [string] $Label)
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    if ($Value -match '\.\.|[;&|<>`]|\$\(') {
        Stop-Session -Message "rejected unexpected $Label" -Code 2 -Class "blocked"
    }
}

function Resolve-RepositoryRoot {
    if ($RepositoryPath) {
        Assert-SafePathText -Value $RepositoryPath -Label "RepositoryPath"
        if (-not (Test-Path -LiteralPath $RepositoryPath)) {
            Stop-Session -Message "repository path does not exist" -Code 2 -Class "blocked"
        }
        return (Resolve-Path -LiteralPath $RepositoryPath).Path
    }
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}

function Assert-MarketOSRepository {
    param([string] $Root)
    Assert-SafePathText -Value $Root -Label "repository"
    $agents = Join-Path $Root "AGENTS.md"
    $scriptsAi = Join-Path $Root "scripts\ai"
    $snapshot = Join-Path $Root "scripts\ai\operator_context_snapshot.py"
    $gitDir = Join-Path $Root ".git"
    if (-not (Test-Path -LiteralPath $agents)) {
        Stop-Session -Message "unexpected repository path: missing AGENTS.md" -Code 2 -Class "blocked"
    }
    if (-not (Test-Path -LiteralPath $scriptsAi)) {
        Stop-Session -Message "unexpected repository path: missing scripts/ai" -Code 2 -Class "blocked"
    }
    if (-not (Test-Path -LiteralPath $snapshot)) {
        Stop-Session -Message "unexpected repository path: missing operator_context_snapshot.py" -Code 2 -Class "blocked"
    }
    if (-not (Test-Path -LiteralPath $gitDir)) {
        Stop-Session -Message "unexpected repository path: not a git worktree" -Code 2 -Class "blocked"
    }
}

function Resolve-Python {
    if ($PythonPath) {
        Assert-SafePathText -Value $PythonPath -Label "PythonPath"
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            Stop-Session -Message "python interpreter not found" -Code 3 -Class "unavailable"
        }
        return @{ Command = (Resolve-Path -LiteralPath $PythonPath).Path; Prefix = @() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Command = $python.Source; Prefix = @() } }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Command = $py.Source; Prefix = @("-3.12") } }
    Stop-Session -Message "no supported python interpreter found (python or py -3.12)" -Code 3 -Class "unavailable"
}

function Invoke-Argv {
    param(
        [string] $Command,
        [string[]] $Arguments,
        [string] $WorkingDirectory,
        [string] $CheckName,
        [string] $SuccessClass = "actual"
    )
    if (-not (Test-Path -LiteralPath $Command)) {
        $resolved = Get-Command $Command -ErrorAction SilentlyContinue
        if (-not $resolved) {
            Write-Classification -Name $CheckName -Class "unavailable" -Code 2
            $script:LastSessionCode = 2
            return
        }
        $Command = $resolved.Source
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Command @Arguments
        $code = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }
    }
    catch {
        Write-Classification -Name $CheckName -Class "failed" -Code 1
        $script:LastSessionCode = 1
        throw
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
    $class = $SuccessClass
    if ($code -eq 2) { $class = "unavailable" }
    elseif ($code -ne 0) { $class = "failed" }
    Write-Classification -Name $CheckName -Class $class -Code $code
    $script:LastSessionCode = $code
}

if ($Timeout -le 0) {
    Stop-Session -Message "timeout must be positive" -Code 2 -Class "blocked"
}

$script:LastSessionCode = 1
$RepoRoot = Resolve-RepositoryRoot
Assert-MarketOSRepository -Root $RepoRoot
$Python = Resolve-Python

switch ($Action) {
    "snapshot" {
        $scriptPath = Join-Path $RepoRoot "scripts\ai\operator_context_snapshot.py"
        $argv = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argv.Add($item) }
        [void]$argv.Add($scriptPath)
        [void]$argv.Add("--json")
        [void]$argv.Add("--repository")
        [void]$argv.Add($RepoRoot)
        [void]$argv.Add("--timeout")
        [void]$argv.Add("$Timeout")
        if ($NoGitHub) { [void]$argv.Add("--no-github") }
        if ($IncludeFrontend) { [void]$argv.Add("--include-frontend") }
        Invoke-Argv -Command $Python.Command -Arguments $argv.ToArray() -WorkingDirectory $RepoRoot -CheckName "snapshot" -SuccessClass "actual"
        exit $script:LastSessionCode
    }
    "readiness" {
        $phase1 = Join-Path $RepoRoot "scripts\phase1_readiness_report.py"
        $stack = Join-Path $RepoRoot "scripts\ai\check_dev_stack.py"
        $argv1 = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argv1.Add($item) }
        [void]$argv1.Add($phase1)
        [void]$argv1.Add("--json")
        Invoke-Argv -Command $Python.Command -Arguments $argv1.ToArray() -WorkingDirectory $RepoRoot -CheckName "phase1_readiness" -SuccessClass "simulated"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $argv2 = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argv2.Add($item) }
        [void]$argv2.Add($stack)
        [void]$argv2.Add("--json")
        Invoke-Argv -Command $Python.Command -Arguments $argv2.ToArray() -WorkingDirectory $RepoRoot -CheckName "development_stack" -SuccessClass "actual"
        exit $script:LastSessionCode
    }
    "select-tests" {
        $scriptPath = Join-Path $RepoRoot "scripts\ai\select_tests.py"
        $argv = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argv.Add($item) }
        [void]$argv.Add($scriptPath)
        [void]$argv.Add("--from-git")
        [void]$argv.Add("--json")
        Invoke-Argv -Command $Python.Command -Arguments $argv.ToArray() -WorkingDirectory $RepoRoot -CheckName "select_tests" -SuccessClass "simulated"
        exit $script:LastSessionCode
    }
    "frontend-check" {
        $frontend = Join-Path $RepoRoot "frontend"
        if (-not (Test-Path -LiteralPath (Join-Path $frontend "package.json"))) {
            Stop-Session -Message "frontend/package.json missing" -Code 2 -Class "unavailable"
        }
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
        if (-not $npm) {
            Stop-Session -Message "npm unavailable" -Code 2 -Class "unavailable"
        }
        Invoke-Argv -Command $npm.Source -Arguments @("test") -WorkingDirectory $frontend -CheckName "frontend_test" -SuccessClass "actual"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        Invoke-Argv -Command $npm.Source -Arguments @("run", "typecheck") -WorkingDirectory $frontend -CheckName "frontend_typecheck" -SuccessClass "actual"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        Invoke-Argv -Command $npm.Source -Arguments @("run", "build") -WorkingDirectory $frontend -CheckName "frontend_build" -SuccessClass "actual"
        exit $script:LastSessionCode
    }
    "backend-check" {
        $argvCompile = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvCompile.Add($item) }
        [void]$argvCompile.Add("-m")
        [void]$argvCompile.Add("compileall")
        [void]$argvCompile.Add("-q")
        [void]$argvCompile.Add("scripts")
        [void]$argvCompile.Add("tests")
        Invoke-Argv -Command $Python.Command -Arguments $argvCompile.ToArray() -WorkingDirectory $RepoRoot -CheckName "compileall" -SuccessClass "actual"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $argvPytest = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvPytest.Add($item) }
        [void]$argvPytest.Add("-m")
        [void]$argvPytest.Add("pytest")
        [void]$argvPytest.Add("-q")
        [void]$argvPytest.Add("tests/ai/test_operator_context_snapshot.py")
        [void]$argvPytest.Add("tests/ai/test_marketos_ai_session.py")
        Invoke-Argv -Command $Python.Command -Arguments $argvPytest.ToArray() -WorkingDirectory $RepoRoot -CheckName "pytest_ai" -SuccessClass "actual"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $argvRuff = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvRuff.Add($item) }
        [void]$argvRuff.Add("-m")
        [void]$argvRuff.Add("ruff")
        [void]$argvRuff.Add("check")
        [void]$argvRuff.Add("scripts/ai")
        [void]$argvRuff.Add("scripts/operators")
        [void]$argvRuff.Add("tests/ai")
        Invoke-Argv -Command $Python.Command -Arguments $argvRuff.ToArray() -WorkingDirectory $RepoRoot -CheckName "ruff" -SuccessClass "actual"
        exit $script:LastSessionCode
    }
    "final-check" {
        $gate = Join-Path $RepoRoot "scripts\ai\run_local_quality_gate.py"
        $prReady = Join-Path $RepoRoot "scripts\ai\pr_readiness_report.py"
        $finish = Join-Path $RepoRoot "scripts\ai\session_finish.py"
        $argvGate = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvGate.Add($item) }
        [void]$argvGate.Add($gate)
        [void]$argvGate.Add("--from-git")
        [void]$argvGate.Add("--json")
        Invoke-Argv -Command $Python.Command -Arguments $argvGate.ToArray() -WorkingDirectory $RepoRoot -CheckName "local_quality_gate" -SuccessClass "simulated"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $argvPr = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvPr.Add($item) }
        [void]$argvPr.Add($prReady)
        [void]$argvPr.Add("--json")
        Invoke-Argv -Command $Python.Command -Arguments $argvPr.ToArray() -WorkingDirectory $RepoRoot -CheckName "pr_readiness" -SuccessClass "simulated"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $argvFinish = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Python.Prefix) { [void]$argvFinish.Add($item) }
        [void]$argvFinish.Add($finish)
        [void]$argvFinish.Add("--dry-run")
        Invoke-Argv -Command $Python.Command -Arguments $argvFinish.ToArray() -WorkingDirectory $RepoRoot -CheckName "session_finish" -SuccessClass "simulated"
        if ($script:LastSessionCode -ne 0) { exit $script:LastSessionCode }
        $git = Get-Command git -ErrorAction SilentlyContinue
        if (-not $git) {
            Stop-Session -Message "git unavailable" -Code 2 -Class "unavailable"
        }
        Invoke-Argv -Command $git.Source -Arguments @("diff", "--check") -WorkingDirectory $RepoRoot -CheckName "git_diff_check" -SuccessClass "actual"
        exit $script:LastSessionCode
    }
}
