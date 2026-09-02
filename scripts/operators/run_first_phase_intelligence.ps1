#requires -Version 5.1
<#
.SYNOPSIS
  Bounded offline first-phase intelligence workflow for Windows operators.

.DESCRIPTION
  Composes existing MarketOS intelligence CLIs into one deterministic, fixture-first
  pipeline. This script is an integration seam only; it does not rank products or
  authorize launch, spend, publishing, or provider mutations.
#>
[CmdletBinding()]
param(
    [string] $OutputDirectory,
    [string] $PythonPath,
    [ValidateRange(1, 25)]
    [int] $MaxCandidates = 5,
    [ValidateRange(1, 10)]
    [int] $MaxSourcesPerCandidate = 3,
    [string] $MarketplaceTrendSeed,
    [string] $MarketplaceTrendImport,
    [string] $ConsumerAttentionSeed,
    [string] $ConsumerAttentionImport,
    [string] $SupplierFeasibilitySeed,
    [string] $SupplierFeasibilityImport,
    [string] $ClientName = "",
    [switch] $AllowNetwork,
    [switch] $AllowPublicNetwork,
    [switch] $WriteSupabase,
    [switch] $UseLiveProvider,
    [switch] $UseModelInference
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Script:ForbiddenOutputSegments = @(
    "artifacts",
    ".git",
    ".env",
    "credentials",
    "secrets",
    "node_modules"
)
$Script:BlockedSwitches = @(
    "AllowNetwork",
    "AllowPublicNetwork",
    "WriteSupabase",
    "UseLiveProvider",
    "UseModelInference"
)

function Stop-Operator {
    param(
        [int] $Code,
        [string] $Message
    )
    [Console]::Error.WriteLine($Message)
    exit $Code
}

function Test-BlockedLiveFlags {
    foreach ($name in $Script:BlockedSwitches) {
        $value = (Get-Variable -Name $name -Scope Script -ErrorAction SilentlyContinue).Value
        if ($value) {
            Stop-Operator -Code 4 -Message "blocked live/network/provider/model flag: -$name"
        }
    }
}

function Resolve-InputPath {
    param([string] $PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $Script:RepoRoot $PathValue))
}

function Test-InputPath {
    param(
        [AllowNull()][string] $PathValue,
        [string] $Label
    )
    if (-not $PathValue) {
        return $null
    }
    if ($PathValue -match '\.\.') {
        Stop-Operator -Code 2 -Message "$Label path traversal is not allowed"
    }
    $resolved = Resolve-InputPath -PathValue $PathValue
    if (-not (Test-Path -LiteralPath $resolved)) {
        Stop-Operator -Code 2 -Message "$Label input does not exist: $resolved"
    }
    $extension = [System.IO.Path]::GetExtension($resolved).ToLowerInvariant()
    if ($extension -ne ".json" -and $extension -ne ".csv") {
        Stop-Operator -Code 2 -Message "$Label input must be .json or .csv: $resolved"
    }
    return $resolved
}

function Test-SafeOutputDirectory {
    param([string] $PathValue)
    if (-not $PathValue) {
        return $null
    }
    if ($PathValue -match '\.\.') {
        Stop-Operator -Code 2 -Message "output path traversal is not allowed"
    }
    $resolved = [System.IO.Path]::GetFullPath($PathValue)
    foreach ($segment in $Script:ForbiddenOutputSegments) {
        if ($resolved -match "(\\|/)$([regex]::Escape($segment))(\\|/|$)") {
            Stop-Operator -Code 2 -Message "output path resolves into forbidden location: $segment"
        }
    }
    $artifactsRoot = [System.IO.Path]::GetFullPath((Join-Path $Script:RepoRoot "artifacts"))
    if ($resolved.StartsWith($artifactsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-Operator -Code 2 -Message "writing into artifacts/ is not allowed"
    }
    return $resolved
}

function Resolve-RepoPython {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            Stop-Operator -Code 3 -Message "python interpreter not found: $PythonPath"
        }
        return @{ Command = $PythonPath; PrefixArgs = @() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Command = $python.Source; PrefixArgs = @() }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Command = $py.Source; PrefixArgs = @("-3.12") }
    }
    Stop-Operator -Code 3 -Message "no supported python interpreter found (python or py -3.12)"
}

function Invoke-PythonStage {
    param(
        [hashtable] $Python,
        [string] $ScriptRelativePath,
        [string[]] $Arguments,
        [string] $StageId
    )
    $scriptPath = Join-Path $Script:RepoRoot $ScriptRelativePath
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Stop-Operator -Code 2 -Message "missing stage script for ${StageId}: $scriptPath"
    }
    $invokeArgs = @()
    $invokeArgs += $Python.PrefixArgs
    $invokeArgs += $scriptPath
    $invokeArgs += $Arguments
    & $Python.Command @invokeArgs | Out-Null
    if ($null -eq $LASTEXITCODE) {
        return 1
    }
    return [int]$LASTEXITCODE
}

function Get-StageClassification {
    param([int] $ExitCode)
    if ($ExitCode -eq 0) { return "actual" }
    return "failed"
}

function Write-DeterministicSummary {
    param(
        [array] $Stages,
        [string] $EvidenceMode,
        [int] $OverallExitCode,
        [string] $OutputDir
    )
    $stageJson = @()
    foreach ($stage in $Stages) {
        $stageJson += "{`"id`":`"$($stage.id)`",`"exit_code`":$($stage.exit_code),`"classification`":`"$($stage.classification)`"}"
    }
    $outputValue = if ($OutputDir) { "`"$($OutputDir.Replace('\','\\'))`"" } else { "null" }
    $summary = "{`"evidence_mode`":`"$EvidenceMode`",`"lane_id`":`"WINDOWS-FIRST-PHASE-RUNNER-01`",`"max_candidates`":$MaxCandidates,`"max_sources_per_candidate`":$MaxSourcesPerCandidate,`"mutated`":false,`"network_calls`":false,`"output_directory`":$outputValue,`"overall_classification`":`"$(Get-StageClassification $OverallExitCode)`",`"overall_exit_code`":$OverallExitCode,`"read_only`":true,`"stages`":[$($stageJson -join ',')]}"
    Write-Output $summary
}

Test-BlockedLiveFlags

$safeOutput = Test-SafeOutputDirectory -PathValue $OutputDirectory
$marketSeed = Test-InputPath -PathValue $MarketplaceTrendSeed -Label "MarketplaceTrendSeed"
$marketImport = Test-InputPath -PathValue $MarketplaceTrendImport -Label "MarketplaceTrendImport"
$consumerSeed = Test-InputPath -PathValue $ConsumerAttentionSeed -Label "ConsumerAttentionSeed"
$consumerImport = Test-InputPath -PathValue $ConsumerAttentionImport -Label "ConsumerAttentionImport"
$supplierSeed = Test-InputPath -PathValue $SupplierFeasibilitySeed -Label "SupplierFeasibilitySeed"
$supplierImport = Test-InputPath -PathValue $SupplierFeasibilityImport -Label "SupplierFeasibilityImport"

$evidenceMode = if ($marketImport -or $consumerImport -or $supplierImport) { "manual_import" } else { "fixture_demo" }
$python = Resolve-RepoPython
$stages = New-Object System.Collections.Generic.List[object]
$overallExit = 0

function Add-StageResult {
    param(
        [string] $Id,
        [int] $ExitCode
    )
    $script:stages.Add([pscustomobject]@{
            id             = $Id
            exit_code      = $ExitCode
            classification = (Get-StageClassification -ExitCode $ExitCode)
        }) | Out-Null
    if ($ExitCode -ne 0 -and $script:overallExit -eq 0) {
        $script:overallExit = $ExitCode
    }
}

function Get-StageOutputPath {
    param([string] $Name)
    if (-not $safeOutput) { return $null }
    $target = Join-Path $safeOutput $Name
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    return $target
}

# 1) Marketplace trend intelligence
$marketArgs = @("--json", "--max-candidates", "$MaxCandidates", "--max-sources-per-candidate", "$MaxSourcesPerCandidate")
if ($marketImport) { $marketArgs += @("--manual-import", $marketImport) }
elseif ($marketSeed) { $marketArgs += @("--candidate-seed", $marketSeed) }
$marketOut = Get-StageOutputPath -Name "marketplace_trend"
if ($marketOut) { $marketArgs += @("--output", $marketOut) }
$marketExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_marketplace_trend_intelligence.py" -Arguments $marketArgs -StageId "marketplace_trend"
Add-StageResult -Id "marketplace_trend" -ExitCode $marketExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 2) Consumer attention intelligence
$consumerArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($consumerImport) { $consumerArgs += @("--manual-import", $consumerImport) }
elseif ($consumerSeed) { $consumerArgs += @("--candidate-seed", $consumerSeed) }
$consumerOut = Get-StageOutputPath -Name "consumer_attention"
if ($consumerOut) { $consumerArgs += @("--output", $consumerOut) }
$consumerExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_consumer_attention_intelligence.py" -Arguments $consumerArgs -StageId "consumer_attention"
Add-StageResult -Id "consumer_attention" -ExitCode $consumerExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 3) Supplier feasibility intelligence
$supplierArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($supplierImport) { $supplierArgs += @("--manual-import", $supplierImport) }
elseif ($supplierSeed) { $supplierArgs += @("--candidate-seed", $supplierSeed) }
$supplierOut = Get-StageOutputPath -Name "supplier_feasibility"
if ($supplierOut) { $supplierArgs += @("--output", $supplierOut) }
$supplierExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_supplier_feasibility_intelligence.py" -Arguments $supplierArgs -StageId "supplier_feasibility"
Add-StageResult -Id "supplier_feasibility" -ExitCode $supplierExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 4) Product opportunity synthesis
$synthesisArgs = @("--json")
if ($marketOut) { $synthesisArgs += @("--marketplace-trend-report", (Join-Path $marketOut "marketplace_trend_report.json")) }
if ($supplierOut) { $synthesisArgs += @("--supplier-feasibility-report", (Join-Path $supplierOut "supplier_feasibility_report.json")) }
if ($consumerOut) { $synthesisArgs += @("--consumer-attention-report", (Join-Path $consumerOut "consumer_attention_report.json")) }
$synthesisOut = Get-StageOutputPath -Name "opportunity_synthesis"
if ($synthesisOut) { $synthesisArgs += @("--output", $synthesisOut) }
$synthesisExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_product_opportunity_synthesis.py" -Arguments $synthesisArgs -StageId "opportunity_synthesis"
Add-StageResult -Id "opportunity_synthesis" -ExitCode $synthesisExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 5) Product validation report
$validationArgs = @("--json")
if ($ClientName) { $validationArgs += @("--client-name", $ClientName) }
if ($marketOut) { $validationArgs += @("--marketplace-trend-report", (Join-Path $marketOut "marketplace_trend_report.json")) }
if ($supplierOut) { $validationArgs += @("--supplier-feasibility-report", (Join-Path $supplierOut "supplier_feasibility_report.json")) }
if ($consumerOut) { $validationArgs += @("--consumer-attention-report", (Join-Path $consumerOut "consumer_attention_report.json")) }
if ($synthesisOut) { $validationArgs += @("--opportunity-synthesis-report", (Join-Path $synthesisOut "opportunity_synthesis_report.json")) }
$validationOut = Get-StageOutputPath -Name "product_validation"
if ($validationOut) { $validationArgs += @("--output", $validationOut) }
$validationExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/generate_product_validation_report.py" -Arguments $validationArgs -StageId "product_validation"
Add-StageResult -Id "product_validation" -ExitCode $validationExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 6) Resource execution governor (offline scenario)
$governorArgs = @("--json", "--scenario", "product_to_launch_pipeline")
$governorOut = Get-StageOutputPath -Name "resource_governor"
if ($governorOut) { $governorArgs += @("--output", $governorOut) }
$governorExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_resource_execution_governor.py" -Arguments $governorArgs -StageId "resource_governor"
Add-StageResult -Id "resource_governor" -ExitCode $governorExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 7) TrustOS control plane (offline defaults)
$trustArgs = @("--json")
$trustOut = Get-StageOutputPath -Name "trustos_control_plane"
if ($trustOut) { $trustArgs += @("--output", $trustOut) }
$trustExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_trustos_control_plane.py" -Arguments $trustArgs -StageId "trustos_control_plane"
Add-StageResult -Id "trustos_control_plane" -ExitCode $trustExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

# 8) Commerce MVP slice (fixture-only advisory packet)
$commerceArgs = @(
    "--use-public-signal-fixture",
    "--query", "offline-fixture-demo",
    "--max-signals", ([string][Math]::Min(10, $MaxCandidates + 2)),
    "--max-candidates", "$MaxCandidates",
    "--json"
)
$commerceExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_commerce_mvp_slice.py" -Arguments $commerceArgs -StageId "commerce_mvp"
Add-StageResult -Id "commerce_mvp" -ExitCode $commerceExit
if ($overallExit -ne 0) {
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $safeOutput
    exit $overallExit
}

Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode 0 -OutputDir $safeOutput
exit 0
