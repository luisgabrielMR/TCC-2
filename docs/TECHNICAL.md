# Documentação — referência técnica

## Fontes atuais

| Fonte | Papel |
| --- | --- |
| `methodological-notes.md` | protocolo implementado da metodologia 15 |
| `validation-methodology-15.md` | evidência dos dez pilotos e seus limites |
| `tcc-compliance-matrix.md` | relação entre implementação e exigências acadêmicas |
| `api-contract.md` e `sql-contract.md` | equivalência HTTP e SQL |
| `database-model.md` | modelo lógico e dataset |
| `environment-versions.md` + preflight por rodada | catálogo e observação efetiva de ambiente |

## Documentos históricos

`experiment-plan.md`, `easy-execution-guide.md`, `runbook.md` e
`measurement-precision-audit.md` contêm contexto de revisões anteriores e podem
citar `fixed_200`, metodologia 8, 9 ou 12. Eles não definem o protocolo atual.
Preservá-los evita apagar o histórico de decisões, mas novos comandos e texto
acadêmico devem usar as fontes atuais, `scripts/benchmark_protocol.py` e
`.env.example`.

O PDF acadêmico aprovado não está versionado neste checkout. Ele é a referência
formal do TCC, mas a implementação deve ser confirmada no código e nas
configurações antes de qualquer afirmação sobre o que foi executado.
