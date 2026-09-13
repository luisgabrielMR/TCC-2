# cAdvisor

O cAdvisor mede quanto de CPU e memória cada container usa. No experimento,
ele acompanha a API ativa, PostgreSQL e Locust. Esses dados ajudam a entender
se a máquina ou o gerador estava sobrecarregado.

Ele não mede uma rota HTTP específica e não prova, sozinho, que não existe
gargalo no banco. A coleta é feita pelo Prometheus e aparece no Grafana.

O ajuste necessário para Docker Desktop e as regras de validação estão em
[TECHNICAL.md](TECHNICAL.md).
