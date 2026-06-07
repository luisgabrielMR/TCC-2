param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("python", "node", "java", "go", "dotnet")]
    [string]$Language,
    [string]$Scenario = "mixed",
    [int]$RunNumber = 1
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root

$serviceDir = "apps/$Language-api"
if ($Language -eq "dotnet") {
    $serviceDir = "apps/dotnet-api"
}

if (-not (Test-Path (Join-Path $serviceDir "Dockerfile"))) {
    Write-Host "A API '$Language' ainda nao foi implementada em $serviceDir."
    Write-Host "A base esta pronta; implemente a API antes de executar a coleta dessa linguagem."
    exit 2
}

$bash = Get-Command bash -ErrorAction SilentlyContinue
if ($bash) {
    & bash "./scripts/run_one_language.sh" $Language $Scenario $RunNumber
    exit $LASTEXITCODE
}

$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    $linuxRoot = (& wsl wslpath -a "$Root").Trim()
    & wsl bash -lc "cd '$linuxRoot' && ./scripts/run_one_language.sh '$Language' '$Scenario' '$RunNumber'"
    exit $LASTEXITCODE
}

throw "Nao encontrei bash nem WSL. Use WSL/Linux para scripts .sh ou instale Git Bash."
