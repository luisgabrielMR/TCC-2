# Resultados — referência técnica

## Organização

Uma rodada segue o padrão `raw/{language}/{scenario}/run_N/`. Ela guarda, entre
outros, estatísticas Locust, falhas, exceções, snapshots por worker, validação
da janela, `postgres_summary.csv`, `cadvisor_summary.csv`, metadata e manifesto
de protocolo.

`scripts/snapshot_integrity.py` só aceita snapshots cujo CSV e hashes coincidem
com a validação e a reconciliação dos workers. `scripts/summarize_results.py`
cria:

- `summary_by_language.csv`;
- `summary_by_endpoint.csv`;
- `summary_scalability.csv`;
- `final_summary.md`.

## Separação de coortes

Os consolidadores filtram por classificação e aceitam `--campaign` para evitar
misturar protocolos. Compare somente a mesma campanha, perfil e protocolo.
`fixed_50` e `fixed_100` são níveis distintos; não some suas linhas.

Campos importantes no metadata: `result_classification`, `load_profile`,
`protocol_sha256`, `campaign_fingerprint`, `execution_order`, limites da janela
e versões/configurações observadas. `run_N` sozinho não identifica uma repetição
oficial, pois pilotos e históricos também ocupam pastas numeradas.

A taxa canônica é requisições concluídas divididas pelo tempo monotônico da
janela validada. P50/P95/P99 vêm dos histogramas de todos os workers. Mediana
de P95 entre rodadas não é o P95 global do conjunto.
