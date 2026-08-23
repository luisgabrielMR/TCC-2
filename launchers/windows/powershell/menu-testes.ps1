param(
    [string]$Action = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root
. (Join-Path $PSScriptRoot "benchmark-common.ps1")

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
    Invoke-BenchmarkPython @($Script)
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

function Invoke-Warmup {
    $environment = Get-BenchmarkEnvironment
    $hostUrl = Get-BenchmarkValue $environment "LOCUST_HOST" "http://host.docker.internal:8000"
    $seconds = [int](Get-BenchmarkValue $environment "WARMUP_DURATION_SECONDS" "300")
    $windowSeconds = [int](Get-BenchmarkValue $environment "WARMUP_STABILITY_WINDOW_SECONDS" "45")
    $maxDrift = [double](Get-BenchmarkValue $environment "WARMUP_MAX_RPS_DRIFT_PERCENT" "10")
    $users = [int](Get-BenchmarkValue $environment "LOCUST_USERS" "50")
    $spawnRate = [int](Get-BenchmarkValue $environment "LOCUST_SPAWN_RATE" "10")
    $waitSeconds = Get-BenchmarkValue $environment "LOCUST_WAIT_SECONDS" "0.1"
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Invoke-BenchmarkWarmup `
        -Environment $environment -Scenario "mixed" -Users $users -SpawnRate $spawnRate `
        -InitialDurationSeconds $seconds `
        -StabilityWindowSeconds $windowSeconds -MaxRpsDriftPercent $maxDrift `
        -WaitSeconds $waitSeconds -HostUrl $hostUrl -ResultRelative "results/raw/warmup/manual_$stamp" | Out-Host
}

function Invoke-RunAllProfile(
    [string]$Profile,
    [int]$OrderOffset = 0,
    [string]$SequenceId = "manual",
    [ValidateSet("pilot", "official")][string]$RunMode = "pilot"
) {
    $languages = @("python", "node", "java", "go", "dotnet")
    for ($index = 0; $index -lt $languages.Count; $index++) {
        $language = $languages[($index + $OrderOffset) % $languages.Count]
        $env:BENCHMARK_SEQUENCE_ID = $SequenceId
        $env:BENCHMARK_ORDER_POSITION = "$($index + 1)"
        & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" `
            -Language $language -Scenario mixed -RunNumber 0 -LoadProfile $Profile -RunMode $RunMode
        if ($LASTEXITCODE -ne 0) { throw "A rodada $language falhou." }
    }
}

function Invoke-RunAll {
    Invoke-RunAllProfile "controlled_50"
}

function Invoke-CapacityBattery {
    $environment = Get-BenchmarkEnvironment
    $repetitions = [int](Get-BenchmarkValue $environment "BENCHMARK_REPETITIONS" "3")
    $profiles = @("controlled_50", "capacity_100", "capacity_200")
    for ($round = 1; $round -le $repetitions; $round++) {
        for ($profileIndex = 0; $profileIndex -lt $profiles.Count; $profileIndex++) {
            $profile = $profiles[$profileIndex]
            $offset = ($round - 1 + $profileIndex * 2) % 5
            Write-Host "Iniciando perfil $profile, repeticao $round/$repetitions, ordem deslocada $offset."
            Invoke-RunAllProfile $profile $offset "${profile}_round_${round}" "official"
        }
    }
    Remove-Item Env:BENCHMARK_SEQUENCE_ID, Env:BENCHMARK_ORDER_POSITION -ErrorAction SilentlyContinue
    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/gerar-graficos.ps1" -NoOpen
    if ($LASTEXITCODE -ne 0) { throw "A geracao final dos resultados falhou." }
}

function Invoke-Summarize {
    Invoke-PythonScript "scripts/summarize_results.py"
}

function Invoke-Charts {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/gerar-graficos.ps1"
    if ($LASTEXITCODE -ne 0) { throw "A geracao dos graficos falhou." }
}

function Invoke-Grafana {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/abrir-grafana.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel abrir o Grafana." }
}

function Invoke-Action([string]$SelectedAction) {
    switch ($SelectedAction) {
        "postgres" { Invoke-Postgres }
        "prepare-db" { Invoke-PrepareDatabase }
        "payloads" { Invoke-PythonScript "database/scripts/generate_test_payloads.py" }
        "validate-db" { Invoke-ValidateDatabase }
        "test-payloads" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/testar-payloads.ps1" -BaseUrl "http://127.0.0.1:8000" }
        "warmup" { Invoke-Warmup }
        "python" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language python -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot }
        "node" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language node -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot }
        "java" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language java -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot }
        "go" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language go -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot }
        "dotnet" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language dotnet -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot }
        "all" { Invoke-RunAll }
        "capacity-100" { Invoke-RunAllProfile "capacity_100" }
        "capacity-200" { Invoke-RunAllProfile "capacity_200" }
        "capacity-all" { Invoke-CapacityBattery }
        "summarize" { Invoke-Summarize }
        "verify" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/verificar-projeto.ps1" }
        "charts" { Invoke-Charts }
        "grafana" { Invoke-Grafana }
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
    Write-Host "7  Piloto Python mixed"
    Write-Host "8  Piloto Node.js mixed"
    Write-Host "9  Piloto Java mixed"
    Write-Host "10 Piloto Go mixed"
    Write-Host "11 Piloto .NET mixed"
    Write-Host "12 Piloto de todas sequencialmente"
    Write-Host "13 Resumir resultados"
    Write-Host "14 Verificar projeto completo"
    Write-Host "15 Gerar graficos e abrir painel"
    Write-Host "16 Piloto de capacidade: 100 usuarios"
    Write-Host "17 Piloto de capacidade: 200 usuarios"
    Write-Host "18 Bateria oficial: 3 repeticoes de 50, 100 e 200"
    Write-Host "19 Abrir Grafana completo"
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
        "14" { Invoke-Action "verify"; Read-Host "Enter para continuar" }
        "15" { Invoke-Action "charts"; Read-Host "Enter para continuar" }
        "16" { Invoke-Action "capacity-100"; Read-Host "Enter para continuar" }
        "17" { Invoke-Action "capacity-200"; Read-Host "Enter para continuar" }
        "18" { Invoke-Action "capacity-all"; Read-Host "Enter para continuar" }
        "19" { Invoke-Action "grafana"; Read-Host "Enter para continuar" }
        "0" { break }
        default { Write-Host "Opcao invalida"; Start-Sleep -Seconds 1 }
    }
}
