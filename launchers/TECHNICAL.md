# Atalhos de execução — referência técnica

## Windows

Os `.bat` chamam scripts PowerShell em `windows/powershell/`. O fluxo principal
está em `menu-testes.ps1`; utilitários comuns ficam em `benchmark-common.ps1`.

| Script | Responsabilidade |
| --- | --- |
| `verificar-projeto.ps1` | builds, contratos, banco, monitoramento e testes integrados |
| `rodar-linguagem.ps1` | prepara banco, inicia uma API, executa warmup/medição e grava metadados |
| `menu-testes.ps1` | encontra a próxima combinação oficial e organiza ordem/retomada |
| `calibrar-gerador.ps1` | diagnóstico health-only opcional |
| `gerar-graficos.ps1` | consolida resultados e abre o painel |
| `testar-payloads.ps1` | chamadas manuais simples à API ativa |

`Get-NextOfficialRoundPlan` usa `OFFICIAL_PROFILES` e `OFFICIAL_ROUNDS`. Para
metodologia 15, são duas campanhas de cinco repetições: `fixed_50` e
`fixed_100`. Cada acionamento mede as cinco APIs de um perfil, com ordem de
linguagens rotacionada; os perfis também alternam a cada rodada.

## Linux/WSL e Bash

Os scripts de `linux-wsl/` são front-ends para os scripts em `../scripts/`.
`scripts/_lib.sh` lê `.env` como pares chave/valor, preservando variáveis de
ambiente já definidas pelo processo chamador.

Use os atalhos ou runners, não execute etapas parciais como se elas fossem uma
rodada oficial. O modo `official` preserva condições, confirmação e metadados.
