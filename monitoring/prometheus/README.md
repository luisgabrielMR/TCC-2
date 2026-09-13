# Prometheus

Prometheus é o ponto de coleta das métricas. Ele visita os outros componentes
a cada segundo, guarda as séries temporárias e entrega esses dados ao
Grafana.

Você pode abri-lo em `http://localhost:9090` quando o perfil de monitoramento
estiver ativo. Em uso normal, não é necessário editar consultas diretamente.

A lista de fontes que ele consulta e seus detalhes estão em
[TECHNICAL.md](TECHNICAL.md).
