# Benchmark de APIs com PostgreSQL

Este projeto compara cinco implementações equivalentes de uma API: Python,
Node.js, Java, Go e C#/.NET. Todas usam o mesmo banco PostgreSQL, fazem as
mesmas operações HTTP e executam SQL direto, sem ORM.

Ele foi organizado para um experimento acadêmico: preparar dados iguais,
executar uma API por vez, gerar carga, medir recursos e guardar evidências.
Não é um sistema de produção.

## Comece por aqui

No Windows, abra `launchers/windows/00_MENU_TESTES.bat`. O menu oferece a
verificação do projeto, a próxima rodada oficial e o acesso aos recursos
avançados. Antes de uma rodada oficial, use a verificação e leia os pilotos;
uma rodada oficial não é um teste rápido.

O ambiente requer Docker Engine 29.5.2 e Docker Compose 5.1.4. As versões são
verificadas antes de uma coleta oficial. Copie `.env.example` para `.env` caso
a configuração local ainda não exista. Não envie `.env` ao Git.

## Como ler a documentação

Cada área tem dois arquivos:

- `README.md`: explicação curta, voltada a quem está conhecendo o projeto.
- `TECHNICAL.md`: detalhes de implementação, parâmetros e limites.

| Se você quer entender... | Leia |
| --- | --- |
| O projeto inteiro e sua arquitetura | [TECHNICAL.md](TECHNICAL.md) |
| Como o Docker reúne os serviços | [infraestrutura](infrastructure/README.md) |
| As cinco APIs | [APIs](apps/README.md) |
| Banco, dados iniciais e restauração | [banco de dados](database/README.md) |
| Carga e perfis do Locust | [Locust](load-tests/locust/README.md) |
| Métricas e dashboards | [monitoramento](monitoring/README.md) |
| Atalhos de execução | [launchers](launchers/README.md) |
| Arquivos de resultados | [resultados](results/README.md) |
| Scripts de apoio | [scripts](scripts/README.md) |
| Contratos e metodologia acadêmica | [documentação](docs/README.md) |

## Estado do experimento

O protocolo atual é a metodologia 15. A campanha oficial inclui `fixed_50` e
`fixed_100`: ambos usam 100 usuários, mas com pacing de 2 s e 1 s,
respectivamente. A carga é fechada; 50 e 100 req/s são tetos nominais e a taxa
efetivamente entregue é sempre registrada. Nenhum dos dois perfis está definido
como referência principal na configuração atual.

Foram executados pilotos técnicos dos dois níveis, mas eles continuam
`non_official`. A campanha científica ainda exige cinco repetições oficiais por
linguagem e por perfil. Leia [a validação local](docs/validation-methodology-15.md)
antes de interpretar ou publicar qualquer resultado.

## Regras importantes

- Meça somente uma API por vez.
- Não mude código, imagens, quotas ou configurações durante uma campanha.
- Não misture resultados de perfis, campanhas ou metodologias diferentes.
- CPU baixa do PostgreSQL não prova que o banco não influenciou a latência.
- Um piloto que funcionou não substitui as repetições oficiais.

As notas metodológicas completas estão em
[docs/methodological-notes.md](docs/methodological-notes.md).
