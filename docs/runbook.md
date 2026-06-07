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
docker compose --profile monitoring up -d postgres postgres-exporter prometheus grafana
```

Prometheus:

```text
http://localhost:9090
```

Grafana:

```text
http://localhost:3000
```

Credenciais locais padrão:

```text
admin / admin
```

## Executar smoke test de API ativa

```bash
./scripts/smoke_test_api.sh http://localhost:8000
```

## Testar payloads manualmente

```bash
./scripts/test_payloads_manually.sh http://localhost:8000
```

## Rodar warmup

```bash
./scripts/run_warmup.sh http://localhost:8000
```

## Rodar uma linguagem

```bash
./scripts/run_one_language.sh python mixed 1
```

O script deve:

1. Resetar banco.
2. Subir somente a API escolhida.
3. Rodar smoke test.
4. Rodar warmup.
5. Resetar banco sem reiniciar a API.
6. Rodar teste principal.
7. Coletar métricas.
8. Exportar resultados.
9. Encerrar a API.

## Encerrar containers

```bash
docker compose down
```

Para remover volumes do banco local:

```bash
docker compose down -v
```

Use remoção de volumes apenas quando quiser apagar o estado local do PostgreSQL.
