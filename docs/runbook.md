# Runbook

## Preparar ambiente

```bash
cp .env.example .env
docker compose up -d postgres
./scripts/setup_database.sh
./scripts/generate_payloads.sh
./scripts/validate_database.sh
```

## Subir monitoramento

```bash
docker compose --profile monitoring up -d postgres postgres-exporter prometheus grafana cadvisor
```

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`, credenciais locais `admin / admin`

Prometheus coleta PostgreSQL pelo `postgres-exporter`. O cAdvisor complementa a visualizacao quando suportado pelo host. A coleta oficial de CPU, memoria e rede usa amostras continuas de `docker stats`, inclusive no Docker Desktop. Nao existe target `/metrics` nas APIs.

## Validar uma API ativa

```bash
./scripts/smoke_test_api.sh http://127.0.0.1:8000
./scripts/test_payloads_manually.sh http://127.0.0.1:8000
```

## Rodar warmup

```bash
./scripts/run_warmup.sh
```

`API_BASE_URL` e usada pelos scripts no host (`http://127.0.0.1:8000`). `LOCUST_HOST` e usada pelo Locust dentro do container (`http://host.docker.internal:8000`).

## Rodar uma linguagem

```bash
./scripts/run_one_language.sh python mixed 1
```

O script reseta o banco, sobe a API, valida o contrato e os endpoints, aquece, reseta sem reiniciar a API, executa o teste principal, coleta metricas, exporta as series do PostgreSQL, reseta novamente o banco e encerra a API mesmo em caso de falha.

Cada rodada grava `docker_stats_raw.csv`, `docker_stats_summary.csv` e os arquivos `prometheus_*.csv` junto aos CSVs do Locust.

No Windows, o mesmo fluxo e nativo em PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/rodar-linguagem.ps1 -Language python -Scenario mixed -RunNumber 1
```

Verificacao completa sem gerar uma rodada oficial de cinco minutos:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/verificar-projeto.ps1
```

## Encerrar containers

```bash
docker compose down
```

Use `docker compose down -v` somente quando quiser apagar o estado local do PostgreSQL.
