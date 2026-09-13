# Locust — referência técnica

## Cenários e pesos

A fonte é `config/scenarios.json`. O cenário `warmup` é um alias de `mixed`.
Pesos representam a parcela de operações em um ciclo completo, não uma
garantia de ordem global de respostas.

| Cenário | Operações e pesos |
| --- | --- |
| `mixed` | cliente individual 1; lista clientes 1; produtos 1; pedido individual 1; cria cliente 1; atualiza cliente 1; cria pedido 1 |
| `read_heavy` | cliente individual 25; lista clientes 20; produtos 20; pedido individual 25; cria cliente 5; atualiza cliente 5 |
| `write_heavy` | cria cliente 25; atualiza cliente 25; cria pedido 30; cliente individual 10; pedido individual 10 |
| `smoke` | sequência curta própria do teste de fumaça |
| `health_only` | somente `GET /health` |

O ciclo do `mixed` tem sete posições: quatro leituras e três escritas, todas
com peso 1. Portanto, um ciclo completo tem 4/7 de leituras (aprox. 57,14%) e
3/7 de escritas (aprox. 42,86%). `GET /health` não pertence a esse cenário
porque não acessa o PostgreSQL. Ele continua nas sequências estáticas `smoke`
e `health_only`, e nos fluxos de disponibilidade, preflight e calibração.
Essa composição é igual para as APIs na mesma execução.

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
em perfis fixos é 99% do teto nominal: 49,5 req/s em `fixed_50` e 99 req/s em
`fixed_100`. O manifesto registra tanto `minimum_delivery_percent` quanto
`minimum_delivery_rps`; os launchers usam esse último valor para classificar a
rodada. Perfis sem taxa fixa não recebem esse critério.

## Reprodutibilidade da carga

`workload_schedule.py` constrói cada ciclo completo repetindo as ações conforme
os pesos e usa o embaralhamento Fisher-Yates de `random.Random`. A semente
positiva `WORKLOAD_SCHEDULE_SEED` (20260913 por padrão) é registrada no
manifesto de protocolo e em `locust_workload_schedule.json`. Para cada worker,
o código deriva uma semente própria por SHA-256 da semente-base, cenário e
índice do worker. Assim, os workers não compartilham estado de agenda, a mesma
semente reproduz a sequência de cada worker e a ordem não fica fixa entre
ciclos. Como todo ciclo contém exatamente os pesos configurados, o embaralhamento
não privilegia posição; apenas o prefixo incompleto no fim pode diferir.

Os usuários também recebem fases iniciais distribuídas no período de pacing.
Isso reduz rajadas sincronizadas no começo.

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
workload. Após validar o CSV final, `record_workload_mix.py` grava
`locust_workload_mix.json` com os pesos planejados e as contagens/proporções
realmente concluídas por endpoint. Percentis P50/P95/P99 são recalculados dos
histogramas dos workers. Os caminhos finais são definidos pelo runner em
`results/raw/.../run_N/`.
