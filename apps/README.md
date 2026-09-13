# As cinco APIs

Há cinco versões da mesma API: Python, Node.js, Java, Go e C#/.NET. Elas têm o
mesmo contrato HTTP, acessam o mesmo PostgreSQL e executam as mesmas operações.
O objetivo é comparar implementações equivalentes, não criar cinco produtos
diferentes.

Durante um teste, somente uma API fica ativa. O menu do Windows escolhe e
encerra a API automaticamente. Para subir uma manualmente, na raiz do projeto:

```bash
docker compose --profile python up -d --build python-api
```

Troque `python` e `python-api` por `node`, `java`, `go` ou `dotnet` quando
necessário. A API responde em `http://127.0.0.1:8000`; um teste simples é:

```bash
curl http://127.0.0.1:8000/health
```

Todas usam no máximo 20 conexões com o banco. Isso mantém o limite comum,
embora cada driver tenha sua própria forma de administrar conexões ociosas.
Veja a [referência técnica das APIs](TECHNICAL.md) para as diferenças reais e
o [contrato HTTP](../docs/api-contract.md) para as rotas.
