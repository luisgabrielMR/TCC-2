# Gerador de carga: Locust

O Locust simula usuários enviando chamadas HTTP para uma API. Ele não compara
as linguagens sozinho: apenas aplica a mesma carga à API que está ativa.

O cenário principal é `mixed`. Ele mede somente as sete operações funcionais
que acessam o PostgreSQL; cada uma tem o mesmo peso e aparece uma vez em cada
ciclo completo embaralhado.

| Operação | Parte da carga |
| --- | ---: |
| Buscar um cliente | 1/7 (aprox. 14,2857%) |
| Listar clientes | 1/7 (aprox. 14,2857%) |
| Listar produtos | 1/7 (aprox. 14,2857%) |
| Buscar um pedido | 1/7 (aprox. 14,2857%) |
| Criar cliente | 1/7 (aprox. 14,2857%) |
| Atualizar cliente | 1/7 (aprox. 14,2857%) |
| Criar pedido | 1/7 (aprox. 14,2857%) |

Assim, quatro das sete operações são leituras (aprox. 57,14%) e três são
escritas (aprox. 42,86%). `GET /health` continua disponível para verificar se a
API está ativa, para smoke, preflight e calibração, mas não entra na janela
medida de `mixed` porque não consulta o banco.

A campanha oficial atual inclui `fixed_50` e `fixed_100`. Ambos usam 100
usuários: o primeiro faz pacing de 2 segundos, até 50 requisições por segundo,
e o segundo usa 1 segundo, até 100 requisições por segundo. Esses valores são
tetos nominais; o relatório registra a taxa realmente entregue. Os perfis
impõem esses parâmetros, mesmo que valores gerais diferentes estejam no `.env`.

Os pilotos são curtos para validar o fluxo. Uma coleta oficial usa 300 segundos
de aquecimento e 300 segundos de medição. Não trate um piloto como resultado
científico final.

As configurações detalhadas, outros cenários e a forma de distribuir as
operações estão em [TECHNICAL.md](TECHNICAL.md).
