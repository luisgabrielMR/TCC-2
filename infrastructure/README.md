# Infraestrutura Docker

Esta área explica como os componentes do experimento são reunidos. Você não
precisa iniciar tudo ao mesmo tempo: o banco fica ativo, uma API é escolhida,
e o monitoramento e o Locust são usados quando necessário.

O arquivo que define o ambiente é `../docker-compose.yml`. Em geral, no Windows,
o menu do projeto é a forma mais segura de iniciar as etapas. Para uma inspeção
manual, por exemplo, o banco pode ser iniciado com:

```bash
docker compose up -d postgres
```

As APIs não devem ficar ativas juntas durante uma coleta. Leia o
[detalhamento técnico](TECHNICAL.md) antes de alterar portas, imagens ou
limites de CPU.
