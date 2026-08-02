param(
    [Parameter(Mandatory=$true)][string]$Category,
    [int]$MaxProducts = 20,
    [int]$IntervalSeconds = 21600,
    [switch]$Once
)
$ErrorActionPreference = "Stop"
$env:MARKETOS_RESEARCH_ONLY = "true"
$env:MARKETOS_RESEARCH_SUPERVISED = "true"
$argsList = @("scripts/research/continuous_research.py", $Category, "--max-products", $MaxProducts, "--interval-seconds", $IntervalSeconds)
if ($Once) { $argsList += "--once" }
Write-Host "Starting MarketOS research-only worker for '$Category'"
python @argsList
