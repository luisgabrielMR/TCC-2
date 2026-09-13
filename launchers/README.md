# Atalhos de execução

Os atalhos tornam a execução mais simples, principalmente no Windows. Comece
por `windows/00_MENU_TESTES.bat`: ele mostra as opções importantes sem exigir
comandos longos.

| Atalho Windows | Para que serve |
| --- | --- |
| `01_VERIFICAR_PROJETO.bat` | verifica banco, APIs, contrato e monitoramento |
| `02_PROXIMA_RODADA_OFICIAL.bat` | executa a próxima rodada que falta |
| `03_ABRIR_GRAFANA.bat` | abre os dashboards |
| `04_MENU_AVANCADO.bat` | preparação, pilotos e tarefas manuais |

Os scripts Linux/WSL têm objetivos equivalentes em `linux-wsl/`. A rodada
oficial pede confirmação e não deve ser usada apenas para testar se o ambiente
abre. Veja a sequência e as regras em [TECHNICAL.md](TECHNICAL.md).
