# Gerador de carga: Locust

O Locust simula usuários enviando chamadas HTTP para uma API. Ele não compara
as linguagens sozinho: apenas aplica a mesma carga à API que está ativa.

O cenário principal é `mixed`. Em cada ciclo de 20 chamadas, ele mantém esta
proporção:

| Operação | Parte da carga |
| --- | ---: |
| Health | 5% |
| Buscar um cliente | 15% |
| Listar clientes | 15% |
| Listar produtos | 15% |
| Buscar um pedido | 15% |
| Criar cliente | 10% |
| Atualizar cliente | 10% |
| Criar pedido | 15% |

A referência principal é `fixed_50`: 100 usuários com um ritmo de uma chamada
a cada 2 segundos, até 50 requisições por segundo. `fixed_100` mantém 100
usuários e reduz o intervalo para 1 segundo, até 100 requisições por segundo.
Esses valores são tetos nominais; o relatório registra a taxa realmente
entregue.

Os pilotos são curtos para validar o fluxo. Uma coleta oficial usa 300 segundos
de aquecimento e 300 segundos de medição. Não trate um piloto como resultado
científico final.

As configurações detalhadas, outros cenários e a forma de distribuir as
operações estão em [TECHNICAL.md](TECHNICAL.md).
