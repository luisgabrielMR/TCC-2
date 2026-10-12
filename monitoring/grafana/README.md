# Grafana

Grafana é a tela de visualização. Ele mostra os dados já coletados pelo
Prometheus; não mede as APIs nem modifica resultados.

Com o monitoramento ativo, abra `http://localhost:3000`. O acesso anônimo é de
leitura. As credenciais locais padrão `admin / admin` só são necessárias para
editar painéis, o que não deve ser feito durante uma campanha.

O dashboard **Resultados Oficiais** segue as métricas da página 14 do TCC
(revisão 28): latência média, P50, P95, P99, vazão, taxa de erro, CPU e memória.
A comparação começa pela latência média e pelos três percentis lado a lado.
O filtro **Latência** alterna média/P50/P95/P99 nos gráficos por execução,
no resumo mínimo–mediana–máximo e nas operações de leitura e escrita.

CPU e memória mostram mínimo, mediana e máximo das médias de cada execução.
Esses extremos não são picos instantâneos nem intervalos de confiança. CPU
usa 100% por núcleo; a escala acompanha os valores observados. Vazão e erros
ficam em uma tabela compacta com os mesmos três resumos, sem repetir um
gráfico de carga quase constante. Os gráficos têm eixos iniciados em zero.
Os painéis não possuem rolagem interna; apenas a página rola.

O filtro de linguagem vale para todos os painéis. `/health` não pertence à
carga `mixed`. Os CSVs originais preservam outros percentis do Locust, mas
os painéis destacam os percentis especificados no TCC: P50, P95 e P99.
Contagens, critérios de validade e protocolo ficam nas evidências da publicação.

**Monitoramento e Diagnóstico** mostra a saúde dos serviços e o PostgreSQL
atual. Expanda a seção Locust durante uma execução; depois que a carga termina,
essa seção pode ficar sem dados ao vivo. Os resultados oficiais continuam disponíveis.

As [figuras e evidências publicadas](../../results/official/2026-10-12_fixed_100_m17/README.md)
podem ser consultadas no GitHub sem iniciar Docker. Detalhes de provisionamento
e filtros estão em [TECHNICAL.md](TECHNICAL.md).
