# Grafana

Grafana é a tela de visualização. Ele mostra os dados já coletados pelo
Prometheus; não mede as APIs nem modifica resultados.

Com o monitoramento ativo, abra `http://localhost:3000`. O acesso anônimo é de
leitura. As credenciais locais padrão `admin / admin` só são necessárias para
editar painéis, o que não deve ser feito durante uma campanha.

Há um painel de resultados oficiais e outro de diagnóstico. Detalhes de
provisionamento e filtros estão em [TECHNICAL.md](TECHNICAL.md).
