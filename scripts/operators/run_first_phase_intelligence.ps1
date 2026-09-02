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
    [switch] $UseModelInference,
    [switch] $ClaimLiveExecution,
    [switch] $LiveValidated
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
    "UseModelInference",
    "ClaimLiveExecution",
    "LiveValidated"
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
            $blockedStage = [pscustomobject]@{
                id             = "preflight"
                exit_code      = 4
                evidence_class = "blocked"
                authority      = "operator_wrapper"
            }
            Write-DeterministicSummary -Stages @($blockedStage) -EvidenceMode "fixture_demo" -OverallExitCode 4 -OutputDir $null -PythonCommand "" -OverallEvidenceClass "blocked"
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

function Exit-UnavailablePython {
    param([string] $Message)
    $unavailableStage = [pscustomobject]@{
        id             = "python_runtime"
        exit_code      = 3
        evidence_class = "unavailable"
        authority      = "operator_wrapper"
    }
    Write-DeterministicSummary -Stages @($unavailableStage) -EvidenceMode "fixture_demo" -OverallExitCode 3 -OutputDir $null -PythonCommand "" -OverallEvidenceClass "unavailable"
    Stop-Operator -Code 3 -Message $Message
}

function Resolve-RepoPython {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            Exit-UnavailablePython -Message "python interpreter not found: $PythonPath"
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
    Exit-UnavailablePython -Message "no supported python interpreter found (python or py -3.12)"
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

function Get-SuccessEvidenceClass {
    param([string] $Mode)
    if ($Mode -eq "manual_import") { return "simulated" }
    return "fixture"
}

function Get-StageClassification {
    param(
        [int] $ExitCode,
        [string] $EvidenceClass = "fixture"
    )
    if ($EvidenceClass -eq "not_run") { return "not_run" }
    if ($EvidenceClass -eq "blocked") { return "blocked" }
    if ($EvidenceClass -eq "unavailable") { return "unavailable" }
    if ($EvidenceClass -eq "fixture") { return "fixture" }
    if ($EvidenceClass -eq "simulated") { return "simulated" }
    if ($EvidenceClass -eq "actual") { return "actual" }
    if ($ExitCode -eq 0) { return "fixture" }
    return "failed"
}

function Get-StageEvidenceClass {
    param(
        [int] $ExitCode,
        [string] $Preset = "",
        [string] $Mode = "fixture_demo"
    )
    if ($Preset) { return $Preset }
    if ($ExitCode -eq 0) { return (Get-SuccessEvidenceClass -Mode $Mode) }
    return "failed"
}

function Resolve-OverallEvidenceClass {
    param(
        [int] $OverallExitCode,
        [string] $EvidenceMode,
        [string] $Requested = "",
        [array] $Stages = @()
    )
    if ($Requested) { return $Requested }
    if ($OverallExitCode -ne 0) { return "failed" }
    foreach ($stage in $Stages) {
        if ($stage.evidence_class -in @("blocked", "unavailable", "failed", "not_run")) {
            return $stage.evidence_class
        }
    }
    return (Get-SuccessEvidenceClass -Mode $EvidenceMode)
}

function Write-DeterministicSummary {
    param(
        [array] $Stages,
        [string] $EvidenceMode,
        [int] $OverallExitCode,
        [string] $OutputDir,
        [string] $PythonCommand,
        [string] $OverallEvidenceClass = ""
    )
    $stageJson = @()
    foreach ($stage in $Stages) {
        $evidenceClass = if ($stage.evidence_class) { $stage.evidence_class } else { Get-StageEvidenceClass -ExitCode $stage.exit_code }
        $classification = Get-StageClassification -ExitCode $stage.exit_code -EvidenceClass $evidenceClass
        $authority = if ($stage.authority) { $stage.authority } else { "composed_cli" }
        $stageJson += "{`"id`":`"$($stage.id)`",`"exit_code`":$($stage.exit_code),`"classification`":`"$classification`",`"evidence_class`":`"$evidenceClass`",`"authority`":`"$authority`"}"
    }
    $outputValue = if ($OutputDir) { "`"$($OutputDir.Replace('\','\\'))`"" } else { "null" }
    $pythonValue = if ($PythonCommand) { "`"$($PythonCommand.Replace('\','\\'))`"" } else { "null" }
    $overallEvidenceClass = Resolve-OverallEvidenceClass -OverallExitCode $OverallExitCode -EvidenceMode $EvidenceMode -Requested $OverallEvidenceClass -Stages $Stages
    if ($overallEvidenceClass -eq "actual") {
        $overallEvidenceClass = (Get-SuccessEvidenceClass -Mode $EvidenceMode)
    }
    $overallClassification = Get-StageClassification -ExitCode $OverallExitCode -EvidenceClass $overallEvidenceClass
    if ($overallClassification -eq "actual") {
        $overallClassification = $overallEvidenceClass
    }
    $summary = "{`"authoritative`":false,`"evidence_authority`":`"offline_planning_only`",`"evidence_mode`":`"$EvidenceMode`",`"fixture_only`":true,`"lane_id`":`"WINDOWS-FIRST-PHASE-EVIDENCE-TRUTH-04`",`"live_validated`":false,`"max_candidates`":$MaxCandidates,`"max_sources_per_candidate`":$MaxSourcesPerCandidate,`"mutated`":false,`"network_calls`":false,`"output_directory`":$outputValue,`"overall_classification`":`"$overallClassification`",`"overall_evidence_class`":`"$overallEvidenceClass`",`"overall_exit_code`":$OverallExitCode,`"python_command`":$pythonValue,`"read_only`":true,`"stages`":[$($stageJson -join ',')]}"
    Write-Output $summary
}

function Add-NotRunStages {
    param([string[]] $StageIds)
    foreach ($stageId in $StageIds) {
        Add-StageResult -Id $stageId -ExitCode 0 -EvidenceClass "not_run" -Authority "composed_cli"
    }
}

$Script:StageOrder = @(
    "marketplace_trend",
    "consumer_attention",
    "supplier_feasibility",
    "opportunity_synthesis",
    "product_validation",
    "resource_governor",
    "trustos_control_plane",
    "commerce_mvp"
)

function Get-RemainingStageIds {
    param([string] $FailedStageId)
    $seen = $false
    $remaining = New-Object System.Collections.Generic.List[string]
    foreach ($stageId in $Script:StageOrder) {
        if ($seen) { $remaining.Add($stageId) | Out-Null }
        if ($stageId -eq $FailedStageId) { $seen = $true }
    }
    return ,$remaining.ToArray()
}

Test-BlockedLiveFlags

$safeOutput = Test-SafeOutputDirectory -PathValue $OutputDirectory
$marketSeed = Test-InputPath -PathValue $MarketplaceTrendSeed -Label "MarketplaceTrendSeed"
$marketImport = Test-InputPath -PathValue $MarketplaceTrendImport -Label "MarketplaceTrendImport"
$consumerSeed = Test-InputPath -PathValue $ConsumerAttentionSeed -Label "ConsumerAttentionSeed"
$consumerImport = Test-InputPath -PathValue $ConsumerAttentionImport -Label "ConsumerAttentionImport"
$supplierSeed = Test-InputPath -PathValue $SupplierFeasibilitySeed -Label "SupplierFeasibilitySeed"
$supplierImport = Test-InputPath -PathValue $SupplierFeasibilityImport -Label "SupplierFeasibilityImport"

$script:evidenceMode = if ($marketImport -or $consumerImport -or $supplierImport) { "manual_import" } else { "fixture_demo" }
$evidenceMode = $script:evidenceMode
$python = Resolve-RepoPython
$pythonCommand = $python.Command
if ($python.PrefixArgs.Count -gt 0) {
    $pythonCommand = "$($python.Command) $($python.PrefixArgs -join ' ')"
}
$stages = New-Object System.Collections.Generic.List[object]
$overallExit = 0

function Add-StageResult {
    param(
        [string] $Id,
        [int] $ExitCode,
        [string] $EvidenceClass = "",
        [string] $Authority = "composed_cli"
    )
    $resolvedEvidenceClass = Get-StageEvidenceClass -ExitCode $ExitCode -Preset $EvidenceClass -Mode $script:evidenceMode
    $script:stages.Add([pscustomobject]@{
            id             = $Id
            exit_code      = $ExitCode
            evidence_class = $resolvedEvidenceClass
            authority      = $Authority
            classification = (Get-StageClassification -ExitCode $ExitCode -EvidenceClass $resolvedEvidenceClass)
        }) | Out-Null
    if ($ExitCode -ne 0 -and $script:overallExit -eq 0) {
        $script:overallExit = $ExitCode
    }
}

function Complete-FailedRun {
    param(
        [string] $FailedStageId,
        [string] $EvidenceMode,
        [string] $OutputDir,
        [string] $PythonCommand
    )
    Add-NotRunStages -StageIds (Get-RemainingStageIds -FailedStageId $FailedStageId)
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $OutputDir -PythonCommand $PythonCommand -OverallEvidenceClass "failed"
    exit $overallExit
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
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "marketplace_trend" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 2) Consumer attention intelligence
$consumerArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($consumerImport) { $consumerArgs += @("--manual-import", $consumerImport) }
elseif ($consumerSeed) { $consumerArgs += @("--candidate-seed", $consumerSeed) }
$consumerOut = Get-StageOutputPath -Name "consumer_attention"
if ($consumerOut) { $consumerArgs += @("--output", $consumerOut) }
$consumerExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_consumer_attention_intelligence.py" -Arguments $consumerArgs -StageId "consumer_attention"
Add-StageResult -Id "consumer_attention" -ExitCode $consumerExit
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "consumer_attention" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 3) Supplier feasibility intelligence
$supplierArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($supplierImport) { $supplierArgs += @("--manual-import", $supplierImport) }
elseif ($supplierSeed) { $supplierArgs += @("--candidate-seed", $supplierSeed) }
$supplierOut = Get-StageOutputPath -Name "supplier_feasibility"
if ($supplierOut) { $supplierArgs += @("--output", $supplierOut) }
$supplierExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_supplier_feasibility_intelligence.py" -Arguments $supplierArgs -StageId "supplier_feasibility"
Add-StageResult -Id "supplier_feasibility" -ExitCode $supplierExit
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "supplier_feasibility" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 4) Product opportunity synthesis
$synthesisArgs = @("--json")
if ($marketOut) { $synthesisArgs += @("--marketplace-trend-report", (Join-Path $marketOut "marketplace_trend_report.json")) }
if ($supplierOut) { $synthesisArgs += @("--supplier-feasibility-report", (Join-Path $supplierOut "supplier_feasibility_report.json")) }
if ($consumerOut) { $synthesisArgs += @("--consumer-attention-report", (Join-Path $consumerOut "consumer_attention_report.json")) }
$synthesisOut = Get-StageOutputPath -Name "opportunity_synthesis"
if ($synthesisOut) { $synthesisArgs += @("--output", $synthesisOut) }
$synthesisExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_product_opportunity_synthesis.py" -Arguments $synthesisArgs -StageId "opportunity_synthesis"
Add-StageResult -Id "opportunity_synthesis" -ExitCode $synthesisExit
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "opportunity_synthesis" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

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
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "product_validation" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 6) Resource execution governor (offline scenario)
$governorArgs = @("--json", "--scenario", "product_to_launch_pipeline")
$governorOut = Get-StageOutputPath -Name "resource_governor"
if ($governorOut) { $governorArgs += @("--output", $governorOut) }
$governorExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_resource_execution_governor.py" -Arguments $governorArgs -StageId "resource_governor"
Add-StageResult -Id "resource_governor" -ExitCode $governorExit -Authority "delegated_governor_cli"
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "resource_governor" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 7) TrustOS control plane (offline defaults)
$trustArgs = @("--json")
$trustOut = Get-StageOutputPath -Name "trustos_control_plane"
if ($trustOut) { $trustArgs += @("--output", $trustOut) }
$trustExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_trustos_control_plane.py" -Arguments $trustArgs -StageId "trustos_control_plane"
Add-StageResult -Id "trustos_control_plane" -ExitCode $trustExit -Authority "delegated_trustos_cli"
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "trustos_control_plane" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 8) Commerce MVP slice (fixture-only advisory packet)
$commerceArgs = @(
    "--use-public-signal-fixture",
    "--query", "offline-fixture-demo",
    "--max-signals", ([string][Math]::Min(10, $MaxCandidates + 2)),
    "--max-candidates", "$MaxCandidates",
    "--json"
)
$commerceExit = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_commerce_mvp_slice.py" -Arguments $commerceArgs -StageId "commerce_mvp"
Add-StageResult -Id "commerce_mvp" -ExitCode $commerceExit -Authority "delegated_commerce_mvp_cli"
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "commerce_mvp" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode 0 -OutputDir $safeOutput -PythonCommand $pythonCommand
exit 0
