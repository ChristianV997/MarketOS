$ErrorActionPreference = "Stop"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "continuous_research.py" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Stopped research workers. No external write was enabled."
