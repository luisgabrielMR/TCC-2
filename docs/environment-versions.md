# Versoes do ambiente

Estado verificado em 23 de agosto de 2026. A fonte reproduzivel e `scripts/preflight.py`: ela consulta Docker, Compose, containers, manifestos, hardware e Git e grava a evidencia em `preflight.json`. Este arquivo documenta o ultimo estado observado; nao substitui a coleta de cada rodada.

## Exigido pelo TCC

| Componente | Versao exigida |
| --- | --- |
| Docker Engine | 29.7.2 |
| Docker Compose | 5.3.1 |
| PostgreSQL | `postgres:17` |
| Locust | `locustio/locust:2.32.6` |
| Prometheus | `prom/prometheus:v2.55.1` |
| Grafana | `grafana/grafana:11.3.0` |
| postgres-exporter | `prometheuscommunity/postgres-exporter:v0.15.0` |
| cAdvisor | `gcr.io/cadvisor/cadvisor:v0.49.1` |
| Python | `python:3.12-slim` |
| Node.js | `node:22-slim` |
| Java | 21 |
| Go | `golang:1.23-bookworm` |
| .NET | 8 |

Todas as imagens de infraestrutura e todos os `FROM` das APIs estao fixados por digest SHA-256. Dependencias usam `requirements.lock`, `package-lock.json`, `pom.xml`, `go.sum` e `packages.lock.json`.

## Detectado neste host

| Item | Valor real |
| --- | --- |
| Sistema operacional | Microsoft Windows 11 Pro, build 26200 |
| CPU | AMD Ryzen 5 3600, 6 nucleos e 12 processadores logicos |
| RAM fisica | 31,93 GiB |
| Armazenamento | Kingston SNV3S2000G NVMe, aproximadamente 1.863 GiB |
| Docker Engine | 29.7.2 |
| Docker Compose | 5.3.1 |
| Alocacao Docker Desktop | 4 processadores logicos e 7,76 GiB |
| Kernel Docker Desktop/WSL2 | 6.18.33.1 |

O Docker Engine e o Compose instalados sao exatamente os registrados pelo experimento, e o `--mode official` nao bloqueia mais por versao. A partir deste ponto a exigencia deixa de ser trocar o Docker Desktop e passa a ser congela-lo: qualquer atualizacao automatica durante a bateria passaria a misturar ambientes entre rodadas.

## Congelamento do ambiente

Nenhuma troca de Docker Desktop e necessaria. Antes de iniciar a bateria oficial:

1. Em `Settings > General`, desative `Always download updates` e `Automatically update components` durante a bateria. Referencia: <https://docs.docker.com/desktop/settings-and-maintenance/settings/>.
2. Mantenha a alocacao experimental declarada em `%UserProfile%\.wslconfig`:

```ini
[wsl2]
processors=4
memory=8GB
```

3. Execute `wsl --shutdown`, abra novamente o Docker Desktop e valide:

```powershell
docker version --format '{{.Server.Version}}'
docker compose version --short
docker info --format 'CPUs={{.NCPU}} memoria_bytes={{.MemTotal}} kernel={{.KernelVersion}} storage={{.Driver}} so={{.OperatingSystem}} cgroup={{.CgroupVersion}}'
```

O resultado esperado para os dois primeiros comandos e `29.7.2` e `5.3.1`, os mesmos valores registrados na Tabela 1 do TCC. A memoria efetiva pode ser ligeiramente menor que 8 GiB por sobrecarga da VM; o valor de `docker info`, e nao os 32 GB fisicos do host, e o valor registrado para os containers. Alterar 4 CPUs/8 GB exige uma nova versao metodologica e repeticao integral das rodadas. A configuracao WSL e documentada em <https://learn.microsoft.com/pt-br/windows/wsl/wsl-config>.

## Runtimes e bibliotecas

O preflight executa `python --version`, `node --version`, `java -version`, `go-api --runtime-version`, `dotnet --list-runtimes` e `locust --version` nas imagens reais. Bibliotecas sao lidas dos manifestos bloqueados. No ultimo inventario construido: Python 3.12.14, Node.js 22.23.2, Java 21.0.11, Go 1.23.x e .NET Runtime 8.0.30. Uma rodada oficial tambem exige `project-verification.json` aprovado no mesmo commit limpo e no ambiente que sera usado na coleta.

Nenhuma API usa ORM. FastAPI, Express e ASP.NET Core Minimal API cuidam apenas de HTTP/JSON; Java usa JDK HttpServer e Go usa `net/http`. SQL, transacoes, rollback e mapeamento permanecem explicitos.

## cAdvisor

O Docker Desktop atual usa o image store containerd. O factory Docker do cAdvisor 0.49.1 procurava `image/overlayfs/layerdb` e descartava cada container; mudar o namespace de cgroup ou desabilitar metricas de disco nao corrigiu a falha. O servico agora desativa esse factory e usa o endpoint containerd no namespace `moby`. Em 23 de agosto de 2026, `scripts/validate_monitoring.py --mode official --api-service python-api` retornou `official_eligible: true`, com uma serie de CPU e uma de memoria para os IDs reais da API, PostgreSQL e Locust. Cgroups genericos como `/`, `/docker` e `/restricted` continuam rejeitados. `docker stats` permanece complementar para diagnostico de pilotos, nunca substituto do requisito do TCC.

## Pool comum

`DB_POOL_MIN=1`, `DB_POOL_MAX=20`, aquisicao `10 s`, ociosidade `60 s` e vida maxima `1800 s`. As diferencas inevitaveis de cada driver sao registradas em `metadata.json`.
