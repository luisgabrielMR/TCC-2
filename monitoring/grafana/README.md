# Grafana

Grafana é a tela de visualização. Ele mostra os dados já coletados pelo
Prometheus; não mede as APIs nem modifica resultados.

Com o monitoramento ativo, abra `http://localhost:3000`. O acesso anônimo é de
leitura. As credenciais locais padrão `admin / admin` só são necessárias para
editar painéis, o que não deve ser feito durante uma campanha.

O dashboard **Resultados Oficiais** compara os resultados consolidados das
APIs: latência média, P50/P95/P99, CPU, memória, operações, vazão e taxa de
erro. As barras mostram, por padrão, medianas por API entre as execuções, com
cores consistentes e eixos iniciados em zero. O filtro **Consolidação**, no
topo da página, alterna esses valores entre **Mediana** (padrão, a usada nos
resultados publicados) e **Média**; os títulos dos painéis mostram qual está
ativa. O filtro **Latência por operação** altera somente os gráficos de
leitura e escrita. CPU usa 100% por núcleo, com escala ajustada ao consumo
observado; memória usa MiB.

O link **Análise complementar** abre um dashboard secundário com latência
por execução e mínimo, valor consolidado e máximo de latência, CPU, memória,
vazão e erro. O valor consolidado segue o filtro **Consolidação** (mediana ou
média); o gráfico por execução não muda. Ali, o filtro **Latência** alterna
média/P50/P95/P99. Essa visão preserva a análise de variabilidade prevista na
página 14 do TCC (28), sem ocupar o painel principal. Os extremos de recursos
são calculados sobre as médias de cada execução; não são picos instantâneos
nem intervalos de confiança.

Os links entre as duas visões preservam os filtros da campanha, da linguagem e
da consolidação.
Não há rolagem interna nos painéis; apenas a página rola. `/health` não
pertence à carga `mixed`. Outros percentis do Locust permanecem nos CSVs
originais. Contagens, critérios de validade e protocolo ficam nas evidências.

**Monitoramento e Diagnóstico** mostra a saúde dos serviços e o PostgreSQL
atual. Expanda a seção Locust durante uma execução; depois que a carga termina,
essa seção pode ficar sem dados ao vivo. Os resultados oficiais continuam disponíveis.

As [figuras e evidências publicadas](../../results/official/2026-10-12_fixed_100_m17/README.md)
podem ser consultadas no GitHub sem iniciar Docker. Detalhes de provisionamento
e filtros estão em [TECHNICAL.md](TECHNICAL.md).
