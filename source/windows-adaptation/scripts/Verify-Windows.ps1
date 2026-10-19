param(
    [string]$Python = "python",
    [string]$Report = "windows-test-receipt.json"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Run this acceptance entry on real Windows." }
if (Test-Path -LiteralPath $Report) { throw "Report already exists; preserve it and choose a new report name." }
$testDirectory = Join-Path $PSScriptRoot "..\tests"
& $Python -X utf8 -m unittest discover -s $testDirectory -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed. No device test was attempted." }
$receipt = [ordered]@{
    source_tests_on_windows = $true
    windows_version = [System.Environment]::OSVersion.VersionString
    architecture = $env:PROCESSOR_ARCHITECTURE
    gui_interaction_verified = $false
    android_runtime_verified = $false
    real_replay_verified = $false
    device_contacted = $false
    network_changed = $false
}
$receipt | ConvertTo-Json | Out-File -LiteralPath $Report -Encoding utf8
Write-Host "Source tests passed on Windows. GUI, debugger, device and replay still need separate validation."
