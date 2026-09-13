# Locust — referência técnica

## Cenários e pesos

A fonte é `config/scenarios.json`. O cenário `warmup` é um alias de `mixed`.
Pesos representam a parcela de operações em um ciclo completo, não uma
garantia de ordem global de respostas.

| Cenário | Operações e pesos |
| --- | --- |
| `mixed` | health 5; cliente individual 15; lista clientes 15; produtos 15; pedido individual 15; cria cliente 10; atualiza cliente 10; cria pedido 15 |
| `read_heavy` | cliente individual 25; lista clientes 20; produtos 20; pedido individual 25; cria cliente 5; atualiza cliente 5 |
| `write_heavy` | cria cliente 25; atualiza cliente 25; cria pedido 30; cliente individual 10; pedido individual 10 |
| `smoke` | sequência curta própria do teste de fumaça |
| `health_only` | somente `GET /health` |

O ciclo do `mixed` tem 20 posições: 1 health, 3 para cada leitura de 15%,
2 para cada escrita de 10% e 3 para criar pedido. Essa composição é igual para
as APIs na mesma execução.

## Perfis

`scripts/benchmark_protocol.py` define os perfis. Os atuais usados pela campanha
são:

| Perfil | Usuários | Spawn | Pacing | Teto nominal |
| --- | ---: | ---: | ---: | ---: |
| `fixed_50` | 100 | 20/s | 2 s | 50 req/s |
| `fixed_100` | 100 | 20/s | 1 s | 100 req/s |

`fixed_125`, `controlled_50`, `capacity_*` e `saturation_*` permanecem
como perfis auxiliares ou históricos. Perfis de saturação usam pacing zero e
não devem ser misturados com a campanha fechada principal.

Com pacing maior que zero, o modelo é `closed_paced_users_v1`: cada usuário
espera sua resposta e então respeita seu próximo ritmo. Logo, a taxa pode cair
se API, banco ou gerador não conseguirem acompanhar. A entrega mínima esperada
em perfis fixos é 97,5% do teto nominal.

## Reprodutibilidade da carga

`workload_schedule.py` usa *smooth weighted round robin* determinístico. O
ciclo é salvo com hash no manifesto. Cada worker recebe um offset diferente; os
usuários também recebem fases iniciais distribuídas no período de pacing. Isso
reduz rajadas sincronizadas no começo.

`payload_sequences.py` reparte criações de clientes em faixas disjuntas por
worker. Atualizações, pedidos e IDs usam ciclos com offsets. O mecanismo não
promete a mesma intercalacão global de respostas: escalonamento e tempo de rede
continuam concorrentes.

## Janela de medição e artefatos

`locustfile.py` começa a janela após `spawning_complete`, reinicia as
estatísticas e usa relógio monotônico. Ao término, cada worker deixa de iniciar
novas requisições; só chamadas já iniciadas podem terminar em drenagem limitada
a cinco segundos, fora da janela principal.

São gravados CSVs de estatísticas, falhas e exceções, snapshots finais por
worker, validação de hashes/reconciliação, limites da janela e o manifesto do
workload. Percentis P50/P95/P99 são recalculados dos histogramas dos workers.
Os caminhos finais são definidos pelo runner em `results/raw/.../run_N/`.
