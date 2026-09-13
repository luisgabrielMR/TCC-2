# Scripts — referência técnica

## Grupos principais

| Grupo | Scripts | Efeito |
| --- | --- | --- |
| Banco | `setup_database.sh`, `reset_db.sh`, `validate_database.sh`, `generate_payloads.sh` | cria/restaura/valida dados e payloads |
| API e contrato | `smoke_test_api.sh`, `contract_test_api.py`, `verify_api_wait_policy.py` | valida comportamento HTTP e equivalência |
| Carga | `run_warmup.sh`, `run_one_language.sh`, `run_all_languages_sequentially.sh`, `run_capacity_battery.sh` | executa cenários e grava resultados |
| Protocolo | `benchmark_protocol.py`, `preflight.py`, `load_generator_calibration.py` | registra condições e verifica prontidão |
| Medição | `finalize_locust_csv.py`, `snapshot_integrity.py`, `validate_measurement_bounds.py`, `validate_warmup_stability.py` | valida janela, workers e estabilidade |
| Monitoramento | `export_prometheus_data.py`, `validate_monitoring.py`, `collect_docker_stats.py` | extrai e verifica métricas |
| Análise | `summarize_results.py`, `generate_results_dashboard.py`, `assess_primary_pilots.py` | consolida e avalia artefatos existentes |

`run_one_language.sh` não é apenas uma chamada ao Locust: ele controla reset,
API, contrato, warmup, medição, exportação, metadados e encerramento. Por isso,
executar Locust isoladamente não produz uma rodada comparável.

`preflight.py --mode official` verifica o ambiente e a proveniência antes da
carga. `assess_primary_pilots.py` é pós-processamento: nunca promove pilotos
nem libera automaticamente uma campanha oficial.
