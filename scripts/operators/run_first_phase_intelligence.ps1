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
            Write-DeterministicSummary -Stages @($blockedStage) -EvidenceMode "fixture_demo" -OverallExitCode 4 -OutputDir $null -PythonCommand "" -OverallEvidenceClass "blocked" -BlockedReason "blocked live/network/provider/model flag: -$name"
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
    Write-DeterministicSummary -Stages @($unavailableStage) -EvidenceMode "fixture_demo" -OverallExitCode 3 -OutputDir $null -PythonCommand "" -OverallEvidenceClass "unavailable" -UnavailableReason $Message
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
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = & $Python.Command @invokeArgs 2>&1
        $exitCode = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }
        $stdoutLines = @()
        foreach ($item in @($raw)) {
            if ($null -eq $item) { continue }
            if ($item -is [System.Management.Automation.ErrorRecord]) {
                $stdoutLines += [string]$item.ToString()
            }
            else {
                $stdoutLines += [string]$item
            }
        }
        return @{
            ExitCode = $exitCode
            StdOut   = ($stdoutLines -join "`n")
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}

function Escape-JsonString {
    param([string] $Value)
    if ($null -eq $Value) { return "" }
    return ($Value.Replace("\", "\\").Replace('"', '\"').Replace("`r", "\r").Replace("`n", "\n").Replace("`t", "\t"))
}

function ConvertTo-CanonicalJson {
    param($Value)
    if ($null -eq $Value) { return "null" }
    if ($Value -is [bool]) {
        if ($Value) { return "true" }
        return "false"
    }
    if ($Value -is [string]) { return '"' + (Escape-JsonString $Value) + '"' }
    if ($Value.GetType().IsValueType -and $Value -isnot [bool]) { return ([string]$Value) }
    if ($Value -is [array]) {
        $items = @($Value | ForEach-Object { ConvertTo-CanonicalJson $_ })
        return "[" + ($items -join ",") + "]"
    }
    if ($Value -is [System.Collections.IList] -and -not ($Value -is [string])) {
        $items = @($Value | ForEach-Object { ConvertTo-CanonicalJson $_ })
        return "[" + ($items -join ",") + "]"
    }
    if ($Value -is [hashtable] -or $Value -is [System.Collections.Specialized.OrderedDictionary]) {
        $keys = @($Value.Keys | Sort-Object)
        $pairs = @()
        foreach ($key in $keys) {
            $pairs += ('"' + (Escape-JsonString ([string]$key)) + '":' + (ConvertTo-CanonicalJson $Value[$key]))
        }
        return "{" + ($pairs -join ",") + "}"
    }
    if ($Value -is [pscustomobject]) {
        $hash = @{}
        foreach ($prop in $Value.PSObject.Properties) {
            $hash[$prop.Name] = $prop.Value
        }
        return (ConvertTo-CanonicalJson $hash)
    }
    return '"' + (Escape-JsonString ([string]$Value)) + '"'
}

function Get-Sha256Hex {
    param([string] $Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-LastJsonObjectFromText {
    param([string] $Text)
    if (-not $Text) { return $null }
    $trim = $Text.Trim()
    try {
        return ($trim | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        $start = $trim.IndexOf("{")
        $end = $trim.LastIndexOf("}")
        if ($start -ge 0 -and $end -gt $start) {
            try {
                return ($trim.Substring($start, $end - $start + 1) | ConvertFrom-Json -ErrorAction Stop)
            }
            catch {
                return $null
            }
        }
        return $null
    }
}

function Test-StdoutSafe {
    param([string] $Text)
    if (-not $Text) { return $true }
    $lower = $Text.ToLowerInvariant()
    foreach ($marker in @("sk-", "begin private key", "bearer ", "ghp_", "xoxb-")) {
        if ($lower.Contains($marker)) { return $false }
    }
    return $true
}

function Get-StageStatusLabel {
    param(
        [int] $ExitCode,
        [string] $EvidenceClass
    )
    if ($EvidenceClass -eq "not_run") { return "not_run" }
    if ($EvidenceClass -eq "blocked") { return "blocked" }
    if ($EvidenceClass -eq "unavailable") { return "unavailable" }
    if ($ExitCode -eq 0) { return "completed" }
    return "failed"
}

function Get-EvidenceLabelForStage {
    param(
        [string] $Mode,
        [string] $StageId
    )
    if ($Mode -eq "manual_import") { return "manual_import" }
    if ($StageId -eq "commerce_mvp") { return "fixture_demo" }
    return "fixture_demo"
}

function Get-InputFixtureIdentity {
    param(
        [string] $StageId,
        [string] $Mode,
        [hashtable] $Inputs
    )
    switch ($StageId) {
        "marketplace_trend" {
            if ($Inputs.market_import) { return (Split-Path -Leaf $Inputs.market_import) }
            if ($Inputs.market_seed) { return (Split-Path -Leaf $Inputs.market_seed) }
            return "builtin_fixture_demo"
        }
        "consumer_attention" {
            if ($Inputs.consumer_import) { return (Split-Path -Leaf $Inputs.consumer_import) }
            if ($Inputs.consumer_seed) { return (Split-Path -Leaf $Inputs.consumer_seed) }
            return "builtin_fixture_demo"
        }
        "supplier_feasibility" {
            if ($Inputs.supplier_import) { return (Split-Path -Leaf $Inputs.supplier_import) }
            if ($Inputs.supplier_seed) { return (Split-Path -Leaf $Inputs.supplier_seed) }
            return "builtin_fixture_demo"
        }
        "commerce_mvp" { return "tests/fixtures/commerce_mvp/public_signals.json" }
        "resource_governor" { return "offline_scenario_product_to_launch_pipeline" }
        "trustos_control_plane" { return "offline_default_controls" }
        default { return "composed_from_prior_stages" }
    }
}

function Get-SafeInt {
    param($Value, [int] $Default = 0)
    if ($null -eq $Value) { return $Default }
    return [int]$Value
}

function Get-BoundedGovernorSummary {
    param($Payload)
    if ($null -eq $Payload) {
        return @{ present = $false; reason = "stdout_not_parsed" }
    }
    $decisionCount = 0
    if ($Payload.PSObject.Properties.Name -contains "decision_count") { $decisionCount = Get-SafeInt $Payload.decision_count }
    $allowedCount = 0
    if ($Payload.PSObject.Properties.Name -contains "allowed_count") { $allowedCount = Get-SafeInt $Payload.allowed_count }
    $hardBlockCount = 0
    if ($Payload.PSObject.Properties.Name -contains "hard_block_count") { $hardBlockCount = Get-SafeInt $Payload.hard_block_count }
    $approvalCount = 0
    if ($Payload.PSObject.Properties.Name -contains "approval_required_count") { $approvalCount = Get-SafeInt $Payload.approval_required_count }
    return @{
        present                 = $true
        decision_count          = $decisionCount
        allowed_count           = $allowedCount
        hard_block_count        = $hardBlockCount
        approval_required_count = $approvalCount
        read_only               = $true
        network_calls           = $false
        scenario                = "product_to_launch_pipeline"
    }
}

function Get-BoundedTrustOsSummary {
    param($Payload)
    if ($null -eq $Payload) {
        return @{ present = $false; reason = "stdout_not_parsed" }
    }
    $publicLaunch = ""
    if ($Payload.PSObject.Properties.Name -contains "public_launch_decision") {
        $publicLaunch = [string]$Payload.public_launch_decision
    }
    $providerActivation = ""
    if ($Payload.PSObject.Properties.Name -contains "provider_activation_decision") {
        $providerActivation = [string]$Payload.provider_activation_decision
    }
    $controlCount = 0
    if ($Payload.PSObject.Properties.Name -contains "control_count") { $controlCount = Get-SafeInt $Payload.control_count }
    $gateCount = 0
    if ($Payload.PSObject.Properties.Name -contains "gate_count") { $gateCount = Get-SafeInt $Payload.gate_count }
    $hardBlockerCount = 0
    if ($Payload.PSObject.Properties.Name -contains "hard_blocker_count") { $hardBlockerCount = Get-SafeInt $Payload.hard_blocker_count }
    $softBlockerCount = 0
    if ($Payload.PSObject.Properties.Name -contains "soft_blocker_count") { $softBlockerCount = Get-SafeInt $Payload.soft_blocker_count }
    return @{
        present                      = $true
        control_count                = $controlCount
        gate_count                   = $gateCount
        hard_blocker_count           = $hardBlockerCount
        soft_blocker_count           = $softBlockerCount
        public_launch_decision       = $publicLaunch
        provider_activation_decision = $providerActivation
        read_only                    = $true
        network_calls                = $false
    }
}

function Get-BoundedDecisionPacket {
    param($Payload)
    if ($null -eq $Payload) {
        return @{ present = $false; reason = "stdout_not_parsed" }
    }
    $run = $null
    if ($Payload.PSObject.Properties.Name -contains "run") {
        $run = $Payload.run
    }
    $status = "unknown"
    if ($Payload.PSObject.Properties.Name -contains "public_source_status" -and $Payload.public_source_status) {
        $status = [string]$Payload.public_source_status
    }
    elseif ($null -ne $run -and $run.PSObject.Properties.Name -contains "status" -and $run.status) {
        $status = [string]$run.status
    }
    $selected = "none"
    if ($Payload.PSObject.Properties.Name -contains "selected_candidate" -and $Payload.selected_candidate) {
        $selected = [string]$Payload.selected_candidate
    }
    $signalCount = 0
    if ($Payload.PSObject.Properties.Name -contains "signal_count") { $signalCount = Get-SafeInt $Payload.signal_count }
    $candidateCount = 0
    if ($Payload.PSObject.Properties.Name -contains "candidate_count") { $candidateCount = Get-SafeInt $Payload.candidate_count }
    return @{
        present              = $true
        public_source_status = $status
        signal_count         = $signalCount
        candidate_count      = $candidateCount
        selected_candidate   = $selected
        read_only            = $true
        advisory             = $true
        mutated              = $false
        network_used         = $false
        contract             = "commerce_mvp_slice_v1"
        operations_cycle     = "not_run"
    }
}

function Read-BoundedReportFile {
    param([string] $Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        return $null
    }
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
        $stageEvidence = Get-StageProperty -Object $stage -Name "evidence_class" -Default ""
        if ($stageEvidence -in @("blocked", "unavailable", "failed", "not_run")) {
            return $stageEvidence
        }
    }
    return (Get-SuccessEvidenceClass -Mode $EvidenceMode)
}

function Get-StageProperty {
    param(
        $Object,
        [string] $Name,
        $Default = $null
    )
    if ($null -eq $Object) { return $Default }
    if ($Object.PSObject.Properties.Name -contains $Name) {
        return $Object.$Name
    }
    return $Default
}

function Write-DeterministicSummary {
    param(
        [array] $Stages,
        [string] $EvidenceMode,
        [int] $OverallExitCode,
        [string] $OutputDir,
        [string] $PythonCommand,
        [string] $OverallEvidenceClass = "",
        [hashtable] $GovernorResult = $null,
        [hashtable] $TrustOsResult = $null,
        [hashtable] $DecisionPacket = $null,
        [string] $BlockedReason = "",
        [string] $UnavailableReason = ""
    )
    $stageManifest = @()
    foreach ($stage in $Stages) {
        $evidenceClass = Get-StageProperty -Object $stage -Name "evidence_class" -Default (Get-StageEvidenceClass -ExitCode (Get-StageProperty -Object $stage -Name "exit_code" -Default 1) -Mode $EvidenceMode)
        $exitCode = [int](Get-StageProperty -Object $stage -Name "exit_code" -Default 1)
        $classification = Get-StageClassification -ExitCode $exitCode -EvidenceClass $evidenceClass
        $authority = Get-StageProperty -Object $stage -Name "authority" -Default "composed_cli"
        $status = Get-StageStatusLabel -ExitCode $exitCode -EvidenceClass $evidenceClass
        $stageId = [string](Get-StageProperty -Object $stage -Name "id" -Default "unknown")
        $evidenceLabel = Get-StageProperty -Object $stage -Name "evidence_label" -Default (Get-EvidenceLabelForStage -Mode $EvidenceMode -StageId $stageId)
        $fixtureIdentity = Get-StageProperty -Object $stage -Name "input_fixture_identity" -Default "unknown"
        $provenance = Get-StageProperty -Object $stage -Name "provenance" -Default $authority
        $freshness = Get-StageProperty -Object $stage -Name "freshness" -Default "not_observed"
        $stageManifest += ,[ordered]@{
                id                     = $stageId
                exit_code              = $exitCode
                status                 = $status
                classification         = $classification
                evidence_class         = $evidenceClass
                evidence_label         = $evidenceLabel
                input_fixture_identity = $fixtureIdentity
                provenance             = $provenance
                freshness              = $freshness
                authority              = $authority
            }
    }
    $overallEvidenceClass = Resolve-OverallEvidenceClass -OverallExitCode $OverallExitCode -EvidenceMode $EvidenceMode -Requested $OverallEvidenceClass -Stages $Stages
    if ($overallEvidenceClass -eq "actual") {
        $overallEvidenceClass = (Get-SuccessEvidenceClass -Mode $EvidenceMode)
    }
    $overallClassification = Get-StageClassification -ExitCode $OverallExitCode -EvidenceClass $overallEvidenceClass
    if ($overallClassification -eq "actual") {
        $overallClassification = $overallEvidenceClass
    }
    $stageArray = @($stageManifest)
    $normalizedOutputDir = if ([string]::IsNullOrWhiteSpace($OutputDir)) { $null } else { $OutputDir }
    $normalizedPython = if ([string]::IsNullOrWhiteSpace($PythonCommand)) { $null } else { $PythonCommand }
    $governorSummary = if ($GovernorResult) { $GovernorResult } else { @{ present = $false; reason = "not_executed" } }
    $trustosSummary = if ($TrustOsResult) { $TrustOsResult } else { @{ present = $false; reason = "not_executed" } }
    $decisionSummary = if ($DecisionPacket) { $DecisionPacket } else { @{ present = $false; reason = "not_executed" } }
    $fingerprintPayload = [ordered]@{
        evidence_mode             = $EvidenceMode
        fixture_only              = $true
        live_validated            = $false
        authoritative             = $false
        max_candidates            = $MaxCandidates
        max_sources_per_candidate = $MaxSourcesPerCandidate
        overall_classification    = $overallClassification
        overall_evidence_class    = $overallEvidenceClass
        stages                    = $stageArray
        governor_result           = $governorSummary
        trustos_result            = $trustosSummary
        decision_packet           = $decisionSummary
    }
    try {
        $fingerprint = Get-Sha256Hex -Text (ConvertTo-CanonicalJson $fingerprintPayload)
    }
    catch {
        Stop-Operator -Code 2 -Message "fingerprint serialization failed: $($_.Exception.Message)"
    }
    $executionEvidence = [ordered]@{
        schema             = "MarketOS.FirstPhaseExecutionEvidence.v1"
        run_mode           = $EvidenceMode
        evidence_label     = (Get-SuccessEvidenceClass -Mode $EvidenceMode)
        provenance         = "offline_composed_cli"
        freshness          = "not_observed"
        blocked_reason     = if ($BlockedReason) { $BlockedReason } else { $null }
        unavailable_reason = if ($UnavailableReason) { $UnavailableReason } else { $null }
        fingerprint        = $fingerprint
    }
    $summary = [ordered]@{
        schema                  = "MarketOS.FirstPhaseOperatorSummary.v1"
        authoritative           = $false
        evidence_authority      = "offline_planning_only"
        evidence_mode           = $EvidenceMode
        fixture_only            = $true
        lane_id                 = "WINDOWS-FIRST-PHASE-EVIDENCE-PACKET-01"
        live_validated          = $false
        max_candidates          = $MaxCandidates
        max_sources_per_candidate = $MaxSourcesPerCandidate
        mutated                 = $false
        network_calls           = $false
        output_directory        = $normalizedOutputDir
        overall_classification  = $overallClassification
        overall_evidence_class  = $overallEvidenceClass
        overall_exit_code       = $OverallExitCode
        python_command          = $normalizedPython
        read_only               = $true
        stages                  = $stageArray
        execution_evidence      = $executionEvidence
        governor_result         = $governorSummary
        trustos_result          = $trustosSummary
        decision_packet         = $decisionSummary
        fingerprint             = $fingerprint
    }
    try {
        $summaryJson = ConvertTo-CanonicalJson $summary
    }
    catch {
        Stop-Operator -Code 2 -Message "summary serialization failed: $($_.Exception.Message)"
    }
    Write-Output $summaryJson
    if ($normalizedOutputDir) {
        $manifestPath = Join-Path $normalizedOutputDir "first_phase_execution_evidence.json"
        [System.IO.File]::WriteAllText($manifestPath, $summaryJson + "`n", [System.Text.UTF8Encoding]::new($false))
    }
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
$script:inputMap = @{
    market_import    = $marketImport
    market_seed      = $marketSeed
    consumer_import  = $consumerImport
    consumer_seed    = $consumerSeed
    supplier_import  = $supplierImport
    supplier_seed    = $supplierSeed
}
$script:governorResult = $null
$script:trustosResult = $null
$script:decisionPacket = $null
$python = Resolve-RepoPython
$pythonCommand = $python.Command
if ($python.PrefixArgs.Count -gt 0) {
    $pythonCommand = "$($python.Command) $($python.PrefixArgs -join ' ')"
}
$stages = @()
$overallExit = 0

function Add-StageResult {
    param(
        [string] $Id,
        [int] $ExitCode,
        [string] $EvidenceClass = "",
        [string] $Authority = "composed_cli",
        [string] $StdOut = ""
    )
    $resolvedEvidenceClass = Get-StageEvidenceClass -ExitCode $ExitCode -Preset $EvidenceClass -Mode $script:evidenceMode
    $fixtureIdentity = Get-InputFixtureIdentity -StageId $Id -Mode $script:evidenceMode -Inputs $script:inputMap
    $evidenceLabel = Get-EvidenceLabelForStage -Mode $script:evidenceMode -StageId $Id
    if (-not (Test-StdoutSafe -Text $StdOut)) {
        Stop-Operator -Code 2 -Message "stage output rejected: secret-shaped payload detected in $Id"
    }
    $parsed = Get-LastJsonObjectFromText -Text $StdOut
    if ($Id -eq "resource_governor" -and $ExitCode -eq 0) {
        $script:governorResult = Get-BoundedGovernorSummary -Payload $parsed
    }
    if ($Id -eq "trustos_control_plane" -and $ExitCode -eq 0) {
        $script:trustosResult = Get-BoundedTrustOsSummary -Payload $parsed
    }
    if ($Id -eq "commerce_mvp" -and $ExitCode -eq 0) {
        $script:decisionPacket = Get-BoundedDecisionPacket -Payload $parsed
    }
    $script:stages += ,[pscustomobject]@{
            id                     = $Id
            exit_code              = $ExitCode
            evidence_class         = $resolvedEvidenceClass
            authority              = $Authority
            classification         = (Get-StageClassification -ExitCode $ExitCode -EvidenceClass $resolvedEvidenceClass)
            evidence_label         = $evidenceLabel
            input_fixture_identity = $fixtureIdentity
            provenance             = $Authority
            freshness              = "not_observed"
        }
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
    Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode $overallExit -OutputDir $OutputDir -PythonCommand $PythonCommand -OverallEvidenceClass "failed" -GovernorResult $script:governorResult -TrustOsResult $script:trustosResult -DecisionPacket $script:decisionPacket
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
$marketRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_marketplace_trend_intelligence.py" -Arguments $marketArgs -StageId "marketplace_trend"
Add-StageResult -Id "marketplace_trend" -ExitCode $marketRun.ExitCode -StdOut $marketRun.StdOut
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "marketplace_trend" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 2) Consumer attention intelligence
$consumerArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($consumerImport) { $consumerArgs += @("--manual-import", $consumerImport) }
elseif ($consumerSeed) { $consumerArgs += @("--candidate-seed", $consumerSeed) }
$consumerOut = Get-StageOutputPath -Name "consumer_attention"
if ($consumerOut) { $consumerArgs += @("--output", $consumerOut) }
$consumerRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_consumer_attention_intelligence.py" -Arguments $consumerArgs -StageId "consumer_attention"
Add-StageResult -Id "consumer_attention" -ExitCode $consumerRun.ExitCode -StdOut $consumerRun.StdOut
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "consumer_attention" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 3) Supplier feasibility intelligence
$supplierArgs = @("--json", "--max-candidates", "$MaxCandidates")
if ($supplierImport) { $supplierArgs += @("--manual-import", $supplierImport) }
elseif ($supplierSeed) { $supplierArgs += @("--candidate-seed", $supplierSeed) }
$supplierOut = Get-StageOutputPath -Name "supplier_feasibility"
if ($supplierOut) { $supplierArgs += @("--output", $supplierOut) }
$supplierRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_supplier_feasibility_intelligence.py" -Arguments $supplierArgs -StageId "supplier_feasibility"
Add-StageResult -Id "supplier_feasibility" -ExitCode $supplierRun.ExitCode -StdOut $supplierRun.StdOut
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "supplier_feasibility" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 4) Product opportunity synthesis
$synthesisArgs = @("--json")
if ($marketOut) { $synthesisArgs += @("--marketplace-trend-report", (Join-Path $marketOut "marketplace_trend_report.json")) }
if ($supplierOut) { $synthesisArgs += @("--supplier-feasibility-report", (Join-Path $supplierOut "supplier_feasibility_report.json")) }
if ($consumerOut) { $synthesisArgs += @("--consumer-attention-report", (Join-Path $consumerOut "consumer_attention_report.json")) }
$synthesisOut = Get-StageOutputPath -Name "opportunity_synthesis"
if ($synthesisOut) { $synthesisArgs += @("--output", $synthesisOut) }
$synthesisRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_product_opportunity_synthesis.py" -Arguments $synthesisArgs -StageId "opportunity_synthesis"
Add-StageResult -Id "opportunity_synthesis" -ExitCode $synthesisRun.ExitCode -StdOut $synthesisRun.StdOut
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
$validationRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/generate_product_validation_report.py" -Arguments $validationArgs -StageId "product_validation"
Add-StageResult -Id "product_validation" -ExitCode $validationRun.ExitCode -StdOut $validationRun.StdOut
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "product_validation" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 6) Resource execution governor (offline scenario)
$governorArgs = @("--json", "--scenario", "product_to_launch_pipeline")
$governorOut = Get-StageOutputPath -Name "resource_governor"
if ($governorOut) { $governorArgs += @("--output", $governorOut) }
$governorRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_resource_execution_governor.py" -Arguments $governorArgs -StageId "resource_governor"
Add-StageResult -Id "resource_governor" -ExitCode $governorRun.ExitCode -Authority "delegated_governor_cli" -StdOut $governorRun.StdOut
if ($governorOut) {
    $governorFile = Read-BoundedReportFile -Path (Join-Path $governorOut "resource_execution_governor_report.json")
    if ($governorFile) { $script:governorResult = Get-BoundedGovernorSummary -Payload $governorFile }
}
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "resource_governor" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 7) TrustOS control plane (offline defaults)
$trustArgs = @("--json")
$trustOut = Get-StageOutputPath -Name "trustos_control_plane"
if ($trustOut) { $trustArgs += @("--output", $trustOut) }
$trustRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_trustos_control_plane.py" -Arguments $trustArgs -StageId "trustos_control_plane"
Add-StageResult -Id "trustos_control_plane" -ExitCode $trustRun.ExitCode -Authority "delegated_trustos_cli" -StdOut $trustRun.StdOut
if ($trustOut) {
    $trustFile = Read-BoundedReportFile -Path (Join-Path $trustOut "trustos_report.json")
    if ($trustFile) { $script:trustosResult = Get-BoundedTrustOsSummary -Payload $trustFile }
}
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "trustos_control_plane" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

# 8) Commerce MVP slice (fixture-only advisory packet)
$commerceArgs = @(
    "--use-public-signal-fixture",
    "--query", "offline-fixture-demo",
    "--max-signals", ([string][Math]::Min(10, $MaxCandidates + 2)),
    "--max-candidates", "$MaxCandidates",
    "--json"
)
$commerceRun = Invoke-PythonStage -Python $python -ScriptRelativePath "scripts/run_commerce_mvp_slice.py" -Arguments $commerceArgs -StageId "commerce_mvp"
Add-StageResult -Id "commerce_mvp" -ExitCode $commerceRun.ExitCode -Authority "delegated_commerce_mvp_cli" -StdOut $commerceRun.StdOut
if ($overallExit -ne 0) { Complete-FailedRun -FailedStageId "commerce_mvp" -EvidenceMode $evidenceMode -OutputDir $safeOutput -PythonCommand $pythonCommand }

Write-DeterministicSummary -Stages $stages -EvidenceMode $evidenceMode -OverallExitCode 0 -OutputDir $safeOutput -PythonCommand $pythonCommand -GovernorResult $script:governorResult -TrustOsResult $script:trustosResult -DecisionPacket $script:decisionPacket
exit 0
