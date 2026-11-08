# Benchmark de APIs com PostgreSQL

Este projeto compara cinco implementações equivalentes de uma API: Python,
Node.js, Java, Go e C#/.NET. Todas usam o mesmo banco PostgreSQL, fazem as
mesmas operações HTTP e executam SQL direto, sem ORM.

Ele foi organizado para um experimento acadêmico: preparar dados iguais,
executar uma API por vez, gerar carga, medir recursos e guardar evidências.
Não é um sistema de produção.

## Como executar e testar — avaliadores

Este README é o LEIAME de execução do projeto. O roteiro abaixo permite
preparar a base e verificar o funcionamento das cinco APIs no Windows, sem
executar as 25 medições da campanha oficial.

### 1. Preparar o ambiente

- Windows com PowerShell e `curl.exe` disponíveis no terminal.
- Docker Desktop iniciado e configurado para containers Linux. O protocolo
  do experimento usa Docker Engine **29.5.2** e Docker Compose **5.1.4**;
  versões divergentes bloqueiam a coleta oficial.
- Python 3 instalado no Windows, disponível como `py -3` ou `python`.
  Recomenda-se Python 3.12 para os scripts de apoio. O Python do container
  não substitui essa instalação local.
- Git para clonar o repositório e registrar a versão do código nos relatórios.
- Acesso à internet na primeira execução para baixar imagens e dependências.
  Para reproduzir as condições do protocolo, disponibilize ao Docker pelo
  menos oito processadores lógicos; veja os limites em [TECHNICAL.md](TECHNICAL.md).

As APIs e o PostgreSQL são executados em containers: não é necessário instalar
separadamente PostgreSQL, Node.js, Java, Go ou .NET no computador.

No PowerShell, confira se os comandos estão disponíveis e se o Docker responde:

```powershell
docker version
docker compose version
py -3 --version
git --version
curl.exe --version
```

Se a instalação do Python não incluir o comando `py`, use `python --version`.
As portas padrão usadas pelo ambiente são 5432, 8000, 8089, 9187, 9090, 3000,
8080 e 9101; elas precisam estar livres para os serviços correspondentes.

### 2. Obter o código e a configuração

Clone o [repositório do projeto](https://github.com/luisgabrielMR/TCC-2):

```powershell
git clone https://github.com/luisgabrielMR/TCC-2.git
Set-Location TCC-2
Copy-Item .env.example .env
```

Se recebeu uma cópia pelo AVA ou baixou um ZIP, extraia todos os arquivos e
abra o PowerShell na pasta que contém `docker-compose.yml` e este README.
Execute apenas a cópia de `.env.example` para `.env`. Se `.env` já existir,
preserve sua configuração. Não envie esse arquivo ao Git.

Os valores de `.env.example` permitem iniciar o ambiente local de teste.
Uma cópia sem o histórico Git permite a avaliação funcional, mas não preserva
a identificação do commit exigida para uma coleta oficial.

### 3. Base de dados disponibilizada

O projeto inclui **dados fictícios e determinísticos**, sem depender de uma
base real ou de um dump externo. O schema, os dados iniciais e os índices
estão em [database/init](database/init); os payloads das requisições estão em
[common/payloads](common/payloads).

A base contém 200 mil clientes, endereços, pedidos e pagamentos; 400 mil itens
de pedido e registros de auditoria; e 100 produtos em cinco categorias.
O procedimento de verificação inicia o PostgreSQL e prepara a base
automaticamente. Não é necessário importar os arquivos SQL manualmente.

**A verificação restaura o banco do projeto várias vezes**, substituindo os
dados inseridos em testes anteriores. Use o banco dedicado do benchmark.
Detalhes estão na [documentação do banco](database/README.md).

### 4. Executar a verificação funcional

Na raiz do projeto, execute:

```powershell
.\launchers\windows\01_VERIFICAR_PROJETO.bat
```

Também é possível abrir esse arquivo com duplo clique ou acessar a verificação
pelo menu `launchers/windows/00_MENU_TESTES.bat`.

O procedimento constrói as cinco APIs, prepara e valida o banco, testa os
oito endpoints de cada implementação (incluindo `/health`), compara contratos
e efeitos no banco, verifica o pool Go, executa carga curta, valida o
monitoramento e executa os testes automatizados. Apenas uma API é testada
por vez. Aguarde todas as oito etapas; a primeira execução também inclui
downloads, builds e preparação de dados, e pode demorar conforme o computador
e a conexão.

### 5. Conferir o resultado

Uma execução aprovada exibe a mensagem iniciada por
`Verificacao piloto concluida: banco, 5 APIs, contrato, pool Go, warmup misto, monitoramento e testes com fixtures aprovados.`

Os arquivos para conferir a execução são:

- `results/raw/verification/<identificador>/`: evidências daquela verificação,
  incluindo contratos, estado do banco, carga e monitoramento.
- `results/summaries/project-verification.json`: relatório da última verificação
  concluída, com `completed: true` e `all_executable_tests_passed: true`.

Confira a data `checked_at` e o caminho `artifact_directory` do relatório,
pois uma tentativa que falhou pode deixar o relatório de uma execução anterior.
Se houver erro, leia a mensagem no terminal; o simples fechamento da janela
ou término de uma etapa não significa aprovação. Logs de build ficam em
`results/summaries/build-logs/`.

Ao finalizar, o verificador encerra as APIs e o monitoramento e tenta restaurar
a base inicial; o PostgreSQL permanece disponível. Para parar os serviços do
projeto depois da avaliação, sem excluir os dados, execute na raiz:

```powershell
docker compose --profile "*" stop
```

### 6. Experimentar uma API manualmente (opcional)

Após a verificação, é possível iniciar uma implementação para consultar suas
rotas. Exemplo com Python:

```powershell
docker compose --profile python up -d --build python-api
```

Aguarde a API iniciar e execute:

```powershell
curl.exe -i http://127.0.0.1:8000/health
curl.exe -i http://127.0.0.1:8000/customers/1
```

Ambas as chamadas devem retornar HTTP 200; a segunda consulta um cliente
fictício no banco. As demais rotas estão no [contrato HTTP](docs/api-contract.md).
Encerre a API antes de iniciar outra implementação:

```powershell
docker compose stop python-api
```

### Avaliação funcional e campanha oficial

A verificação acima é uma execução piloto (`non_official`): serve para testar
o projeto e não substitui as medições científicas. A reprodução da campanha
usa `launchers/windows/02_PROXIMA_RODADA_OFICIAL.bat`, com confirmação,
requisitos de ambiente e Git limpo. Cada acionamento executa uma rodada de
cinco APIs; são cinco rodadas para completar as 25 execuções, com 300 segundos
de aquecimento e 300 segundos de medição por API, além da preparação.

**Recomendação opcional para novas execuções:** reinicie o computador antes
da primeira rodada e entre rodadas completas iniciadas pelo atalho. Após cada
reinicialização, abra o Docker Desktop, aguarde o Engine ficar disponível e
o sistema estabilizar, feche programas desnecessários e inicie a próxima
rodada. Adote o mesmo procedimento em todas as rodadas e registre se houve
reinicialização. Cada rodada contém cinco execuções de API; não reinicie o
computador enquanto o atalho estiver executando essa sequência. Essa prática
não é exigida nem automatizada pelos scripts e não substitui a restauração
do banco ou o aquecimento previstos no protocolo.

Para essa reprodução, consulte os [atalhos de execução](launchers/README.md)
e o [passo a passo da campanha](launchers/windows/passo%20a%20passo.txt).
Os [resultados oficiais já publicados](results/official/2026-10-12_fixed_100_m17/README.md)
podem ser consultados sem iniciar uma nova campanha.

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

O protocolo atual é a metodologia 17. Conforme o TCC, a campanha oficial usa
somente `fixed_100`, com 100 usuários, subida de 20 usuários/s e pacing de 1 s.
A carga é fechada; 100 req/s é um teto nominal e a taxa efetivamente entregue
é sempre registrada. São cinco rodadas de cinco APIs, totalizando 25 execuções.

Nas rodadas oficiais, a CPU e a memória do cAdvisor para API, PostgreSQL e
Locust devem cobrir ao menos 95% da janela medida. Essa completude é independente
da entrega mínima de carga; lacunas temporais acima de 1,5 s também invalidam a
evidência de monitoramento.

A campanha oficial foi concluída entre 10 e 12 de outubro de 2026: **25
execuções, 749.796 requisições e zero falhas registradas pelo Locust**.
Os [resultados oficiais](results/official/2026-10-12_fixed_100_m17/README.md)
reúnem gráficos, CSVs, protocolo, commit medido e evidências originais com hashes.
As figuras mostram também a variação entre as cinco repetições; não constituem
um ranking universal das linguagens.

Os pilotos anteriores continuam `non_official` e não entram nessa publicação.
A [validação local histórica](docs/validation-methodology-15.md) documenta a
preparação; os resultados publicados preservam a metodologia 17 e o commit da coleta.

## Regras importantes

- Meça somente uma API por vez.
- Não mude código, imagens, quotas ou configurações durante uma campanha.
- Não misture resultados de perfis, campanhas ou metodologias diferentes.
- CPU baixa do PostgreSQL não prova que o banco não influenciou a latência.
- Um piloto que funcionou não substitui as repetições oficiais.

As notas metodológicas completas estão em
[docs/methodological-notes.md](docs/methodological-notes.md).
