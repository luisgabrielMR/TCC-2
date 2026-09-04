$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\launchers\windows\powershell\benchmark-common.ps1")
$script:BenchmarkRoot = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString("N"))

function Start-Sleep { param($Seconds) }
function docker {
    $script:calls++
    if ($script:failure -eq "network" -and $script:calls -eq 1 -or $script:failure -eq "persistent") {
        Write-Output '#2 ERROR: failed to do request: Head "https://registry-1.docker.io/v2/library/test": dial tcp: lookup registry-1.docker.io: no such host'
        $global:LASTEXITCODE = 1
    }
    elseif ($script:failure -eq "compile") {
        Write-Output 'ERROR: compilation failed: missing symbol'
        $global:LASTEXITCODE = 1
    }
    else {
        Write-Output 'Built'
        $global:LASTEXITCODE = 0
    }
}

foreach ($case in @("success", "network", "persistent", "compile")) {
    $script:failure = $case
    $script:calls = 0
    $caught = $null
    try { Invoke-BenchmarkCompose -Arguments @("--profile", "python", "build", "python-api") }
    catch { $caught = $_.Exception.Message }
    $expected = @{ success = 1; network = 2; persistent = 3; compile = 1 }[$case]
    if ($script:calls -ne $expected) { throw "${case}: expected $expected calls, got $script:calls" }
    if ($case -in @("persistent", "compile")) {
        if (-not $caught -or $caught -notmatch 'Log: .*\.log' -or $caught -notmatch 'ERROR') {
            throw "${case}: missing error and diagnostic log: $caught"
        }
    }
    elseif ($caught) { throw $caught }
    Write-Host "PASS: $case"
}
$logs = @(Get-ChildItem -LiteralPath (Join-Path $script:BenchmarkRoot "results\summaries\build-logs") -Filter *.log)
if ($logs.Count -ne 7) { throw "Expected seven preserved attempt logs, got $($logs.Count)" }
