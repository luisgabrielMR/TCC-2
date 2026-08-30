---
name: rodada-oficial
description: Sequencia completa para produzir uma rodada oficial do benchmark e os portoes que precisam passar antes dela. Cobre verificacao no commit limpo, preflight, calibracao do gerador, bateria com repeticoes e ordem rotacionada, e consolidacao. Use ao preparar, executar ou destravar a coleta oficial, e quando o preflight bloquear.
when_to_use: Pedidos como "rodar a bateria oficial", "preparar a coleta", "o preflight bloqueou", "por que a rodada ficou non_official", "como gerar os resultados finais", "quero comecar as rodadas", "destravar o preflight"
---

# Rodada oficial

Nada disso roda sem o Docker Desktop aberto. Ordem obrigatoria — cada passo depende do anterior estar valido **no mesmo commit limpo**.

## 1. Arvore limpa e commitada

`official` exige `git_dirty: false` e um `project-verification.json` gerado nesse mesmo commit. Qualquer arquivo rastreado alterado depois invalida a verificacao. `results/**` e ignorado pelo Git e nao suja a arvore.

## 2. Verificacao completa

```
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/verificar-projeto.ps1
```

Constroi as cinco imagens, reseta o banco, valida OpenAPI, schema e indices, roda o contrato canonico nas cinco e compara o estado final.

**O portao que importa:** em `results/raw/verification/<timestamp>/`, os cinco `database-state-*.json` tem que ter hash SHA-256 identico. Hash diferente significa que as implementacoes divergiram — pare aqui.

## 3. Preflight oficial

```
python scripts/preflight.py --mode official --output results/summaries/preflight-official.json
```

Esperado: `official_blockers: []` e `environment_eligible_for_official_run: true`. Bloqueios tipicos e o que fazem:

- versao de Docker ou Compose diferente da Tabela 1 do TCC aprovado — nao mude a constante para acomodar o host; primeiro e necessaria uma revisao formal do TCC;
- Docker expondo menos processadores logicos que o exigido — falta capacidade agregada para as cotas simultaneas; ajuste `processors` no `%UserProfile%\.wslconfig` e rode `wsl --shutdown`;
- `cpus` do Compose diferente de `EXPECTED_CPU_LIMITS`;
- arvore suja ou verificacao de outro commit;
- calibracao do gerador ausente.

## 4. Calibracao do gerador

```
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/calibrar-gerador.ps1
```

Carga so de `GET /health`, sem pacing, em degraus de usuarios. Descobre o teto do proprio Locust. Uma rodada so vale se ficar abaixo de 80% dessa capacidade e com a CPU do gerador com folga — senao o numero medido e do gerador, nao da API. Se o teto ficar abaixo do que as APIs aguentam, aumente `LOCUST_PROCESSES` e a cota de CPU do container, e recalibre.

## 5. Bateria

Perfil de taxa fixa (`fixed_200`) e escada de saturacao respondem perguntas diferentes e nao se misturam na mesma coorte.

No Windows, `launchers/windows/02_PROXIMA_RODADA_OFICIAL.bat` executa a proxima rodada oficial ainda incompleta e retoma sem sobrescrever. Cada rodada mede as cinco linguagens uma por vez, com ordem rotacionada. Apenas uma API ativa por vez, sempre.

`scripts/run_capacity_battery.sh` roda a escada de saturacao.

## 6. Consolidar

```
python scripts/summarize_results.py
python scripts/generate_results_dashboard.py
```

Publicam somente `official`. Se os CSVs sairem so com cabecalho, nenhuma rodada passou nos portoes — leia `result_classification`, `measurement_stability`, `rate_target_met` e `generator_headroom_met` no `metadata.json` antes de mexer em qualquer outra coisa.

## Regras que nao se negociam

- Desligue a atualizacao automatica do Docker Desktop antes de comecar. Uma atualizacao no meio mistura ambientes entre rodadas.
- Cinco rodadas por linguagem no perfil oficial `fixed_200`, com ordem rotacionada. Menos que isso e preliminar na metodologia 7.
- Rodada instavel, fora do alvo de taxa ou sem folga de gerador nao vira oficial por insistencia — vira oficial por corrigir a causa.
- Nunca promova `pilot` ou `legacy` a oficial no consolidado.
