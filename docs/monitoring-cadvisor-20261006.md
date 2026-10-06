# Falha de continuidade do cAdvisor em 06/10/2026

Diagnóstico baseado nos artefatos existentes em
`results/raw/python/mixed_fixed_50/run_3`, commit `6089c26`.
Nenhuma nova carga foi executada para este diagnóstico.

A API concluiu 14.999 requisições sem falhas. A janela de medição foi validada,
mas a exportação rejeitou CPU e memória por descontinuidade temporal.
Os quatro targets do Prometheus ficaram `up=1` durante a janela exportada.

| Componente | Cobertura válida de CPU e memória | Maior intervalo |
| --- | ---: | ---: |
| Python API | 35,372057% | 1,998 s |
| PostgreSQL | 41,536355% | 1,997 s |
| Locust da medição | 42,935921% | 1,996 s |

Cobertura válida conta apenas os intervalos aceitos de até 1,5 s, sem reset.
Ela não representa percentual de tempo em que o endpoint de monitoramento
ficou indisponível. Os arquivos originais são preservados; este diagnóstico
não promove a tentativa a resultado oficial.

## Causa e correção

No [código do cAdvisor 0.49.1](https://github.com/google/cadvisor/blob/v0.49.1/manager/container.go#L443-L467),
`nextHousekeepingInterval` aplica jitter de fator 1 independentemente de
`allow_dynamic_housekeeping`. Por isso, a base de 1 s permite esperas próximas
de 2 s. O [exportador dessa versão](https://github.com/google/cadvisor/blob/v0.49.1/metrics/prometheus.go#L1854-L1868)
publica os timestamps das amostras internas; target saudável não prova
amostragem a cada segundo.

A configuração corrigida usa base interna de 200 ms. O jitter permite esperas
nominais entre 200 e 400 ms, além do custo de coleta/escalonamento. Com scrape
de 1 s, o limite nominal conservador de variação entre timestamps é 1,4 s,
deixando margem abaixo de 1,5 s. Isso é dimensionamento da configuração, não
garantia empírica. As versões das imagens, scrape de 1 s, timestamps originais,
95% de cobertura e rejeição de gaps superiores a 1,5 s são preservados.

O manifesto e os metadados registram a base interna e o fator de jitter.
A mudança gera outro fingerprint de campanha. A documentação metodológica
agora distingue a atualização interna do cAdvisor do scrape do Prometheus.

O preflight passou a avaliar 30 s de amostras reais antes da carga, com os
mesmos cálculos de qualidade da exportação. A exportação grava cobertura,
gaps, resets e motivos em `cadvisor-validation.json`; a etapa da falha fica em
`prometheus-validation.json`. O launcher preserva o motivo informado no stderr.

## Limite da validação desta correção

Foram analisados os arquivos já gravados e a sintaxe das alterações. A suíte
automatizada e novas cargas não foram executadas, conforme solicitado.
A correção da configuração ainda precisa ser observada na execução manual;
um preflight aprovado não garante continuidade durante toda a carga.

## Revisão adicional do fluxo antes da retomada

A revisão estática da inicialização, coleta, exportação, classificação e
encerramento identificou mais três problemas corrigidos:

- Os runners PowerShell e Bash gravavam `non_official` quando faltava folga de
  CPU do PostgreSQL, mas terminavam com sucesso. Agora retornam erro depois de
  preservar os metadados; o menu não anuncia uma rodada oficial concluída.
- No Windows, `up -d` precedido por `--profile` não recebia as tentativas de
  inicialização já previstas. `up --build` também passava fora do tratamento
  de falhas transitórias de rede do build. Ambos passam pelos caminhos
  correspondentes, com limites de tentativas e logs do build.
- A chamada de `docker stats` não tinha timeout. Ela passa a encerrar com erro
  após 15 segundos sem resposta, evitando espera indefinida no coletor e no
  encerramento do runner Bash. Isso não substitui nem flexibiliza cAdvisor.

Foram conferidas as sintaxes de 41 arquivos Python, oito PowerShell e 23 Bash,
além de `git diff --check`. Nenhuma suíte de testes, carga, reset de banco ou
inicialização de serviço foi executada nesta revisão. A validação de sintaxe
não comprova o comportamento durante uma medição; os bloqueios do protocolo
continuam obrigatórios na execução manual.
