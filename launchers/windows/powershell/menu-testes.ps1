param(
    [string]$Action = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root

function Read-EnvFile {
    $map = @{}
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        $envPath = Join-Path $Root ".env.example"
    }
    if (Test-Path $envPath) {
        Get-Content $envPath | ForEach-Object {
            if ($_ -match '^\s*#') { return }
            if ($_ -match '^\s*$') { return }
            if ($_ -match '^\s*([^=]+)=(.*)$') {
                $map[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
    }
    return $map
}

$EnvMap = Read-EnvFile

function Get-EnvValue([string]$Name, [string]$Default) {
    if ($EnvMap.ContainsKey($Name)) { return $EnvMap[$Name] }
    return $Default
}

function Invoke-PythonScript([string]$Script) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py $Script
        return
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python $Script
        return
    }
    throw "Python nao encontrado no PATH. Instale Python 3 para executar $Script."
}

function Wait-Postgres {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Write-Host "Aguardando PostgreSQL..."
    for ($i = 0; $i -lt 60; $i++) {
        docker compose exec -T postgres pg_isready -U $user -d $db *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL pronto."
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL nao ficou pronto dentro do tempo esperado."
}

function Invoke-Postgres {
    docker compose up -d postgres
}

function Invoke-PrepareDatabase {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Invoke-Postgres
    Wait-Postgres
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/001_schema.sql
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/002_seed_base_data.sql
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/003_indexes.sql
}

function Invoke-ValidateDatabase {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Invoke-Postgres
    Wait-Postgres
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/scripts/validate_database.sql
}

function Invoke-BashScript([string]$Script, [string[]]$Args = @()) {
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($bash) {
        & bash $Script @Args
        return
    }
    $wsl = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wsl) {
        $linuxRoot = (& wsl wslpath -a "$Root").Trim()
        $quotedArgs = ($Args | ForEach-Object { "'$($_ -replace "'", "'\''")'" }) -join " "
        & wsl bash -lc "cd '$linuxRoot' && bash '$Script' $quotedArgs"
        return
    }
    throw "Nao encontrei bash nem WSL. Use os scripts .sh no WSL/Linux ou instale Git Bash."
}

function Invoke-Warmup {
    Invoke-BashScript "./scripts/run_warmup.sh" @("http://localhost:8000")
}

function Invoke-RunAll {
    Invoke-BashScript "./scripts/run_all_languages_sequentially.sh" @("mixed", "1")
}

function Invoke-Summarize {
    Invoke-PythonScript "scripts/summarize_results.py"
}

function Invoke-Action([string]$SelectedAction) {
    switch ($SelectedAction) {
        "postgres" { Invoke-Postgres }
        "prepare-db" { Invoke-PrepareDatabase }
        "payloads" { Invoke-PythonScript "database/scripts/generate_test_payloads.py" }
        "validate-db" { Invoke-ValidateDatabase }
        "test-payloads" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/testar-payloads.ps1" -BaseUrl "http://localhost:8000" }
        "warmup" { Invoke-Warmup }
        "python" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language python -Scenario mixed -RunNumber 1 }
        "node" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language node -Scenario mixed -RunNumber 1 }
        "java" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language java -Scenario mixed -RunNumber 1 }
        "go" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language go -Scenario mixed -RunNumber 1 }
        "dotnet" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language dotnet -Scenario mixed -RunNumber 1 }
        "all" { Invoke-RunAll }
        "summarize" { Invoke-Summarize }
        default { throw "Acao desconhecida: $SelectedAction" }
    }
}

if ($Action) {
    Invoke-Action $Action
    exit $LASTEXITCODE
}

while ($true) {
    Clear-Host
    Write-Host "Menu de testes - TCC PostgreSQL Backend Benchmark"
    Write-Host ""
    Write-Host "1  Subir PostgreSQL"
    Write-Host "2  Preparar banco"
    Write-Host "3  Gerar payloads"
    Write-Host "4  Validar banco"
    Write-Host "5  Testar payloads da API ativa"
    Write-Host "6  Rodar warmup da API ativa"
    Write-Host "7  Rodar Python mixed"
    Write-Host "8  Rodar Node.js mixed"
    Write-Host "9  Rodar Java mixed"
    Write-Host "10 Rodar Go mixed"
    Write-Host "11 Rodar .NET mixed"
    Write-Host "12 Rodar todas sequencialmente"
    Write-Host "13 Resumir resultados"
    Write-Host "0  Sair"
    Write-Host ""
    $choice = Read-Host "Escolha"
    switch ($choice) {
        "1" { Invoke-Action "postgres"; Read-Host "Enter para continuar" }
        "2" { Invoke-Action "prepare-db"; Read-Host "Enter para continuar" }
        "3" { Invoke-Action "payloads"; Read-Host "Enter para continuar" }
        "4" { Invoke-Action "validate-db"; Read-Host "Enter para continuar" }
        "5" { Invoke-Action "test-payloads"; Read-Host "Enter para continuar" }
        "6" { Invoke-Action "warmup"; Read-Host "Enter para continuar" }
        "7" { Invoke-Action "python"; Read-Host "Enter para continuar" }
        "8" { Invoke-Action "node"; Read-Host "Enter para continuar" }
        "9" { Invoke-Action "java"; Read-Host "Enter para continuar" }
        "10" { Invoke-Action "go"; Read-Host "Enter para continuar" }
        "11" { Invoke-Action "dotnet"; Read-Host "Enter para continuar" }
        "12" { Invoke-Action "all"; Read-Host "Enter para continuar" }
        "13" { Invoke-Action "summarize"; Read-Host "Enter para continuar" }
        "0" { break }
        default { Write-Host "Opcao invalida"; Start-Sleep -Seconds 1 }
    }
}
