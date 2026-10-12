# Grafana

Grafana é a tela de visualização. Ele mostra os dados já coletados pelo
Prometheus; não mede as APIs nem modifica resultados.

Com o monitoramento ativo, abra `http://localhost:3000`. O acesso anônimo é de
leitura. As credenciais locais padrão `admin / admin` só são necessárias para
editar painéis, o que não deve ser feito durante uma campanha.

O dashboard **Resultados Oficiais** mostra tempo médio de resposta, P95 por
execução, CPU, memória e latência das operações de leitura e escrita. Usa
barras com eixos comuns iniciados em zero, cores fixas por linguagem e valores
visíveis. A escala de CPU acompanha o consumo observado, não a cota máxima.
Não há tabelas nem rolagem dentro dos gráficos; apenas a página rola.

O filtro de linguagem vale para todos os gráficos. O filtro de latência da
operação alterna média/P50/P95/P99 nos gráficos de leitura e escrita.
`/health` não pertence à carga `mixed` e não aparece na comparação.
As métricas agregadas usam medianas; os detalhes estão nas descrições dos painéis.
Contagens, critérios de validade e protocolo ficam nas evidências da publicação.

**Monitoramento e Diagnóstico** mostra a saúde dos serviços e o PostgreSQL
atual. Expanda a seção Locust durante uma execução; depois que a carga termina,
essa seção pode ficar sem dados ao vivo. Os resultados oficiais continuam disponíveis.

As [figuras e evidências publicadas](../../results/official/2026-10-12_fixed_100_m17/README.md)
podem ser consultadas no GitHub sem iniciar Docker. Detalhes de provisionamento
e filtros estão em [TECHNICAL.md](TECHNICAL.md).
