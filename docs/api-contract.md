# Contrato da API

Todas as APIs devem retornar JSON equivalente, códigos HTTP equivalentes e mensagens de erro padronizadas. Os nomes de campos JSON usam `camelCase`.

Todos os identificadores JSON sao numeros inteiros. Datas usam UTC no formato `YYYY-MM-DDTHH:MM:SSZ`, sem fracao de segundo. Erros de validacao acumulam os campos invalidos em ordem deterministica; campos aninhados usam nomes como `address.street`, `address.isDefault` e `payment.method`.

## Resposta de erro

Formato obrigatório:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request payload",
    "details": []
  }
}
```

Códigos padronizados:

- `VALIDATION_ERROR`: payload, parâmetro ou campo inválido.
- `NOT_FOUND`: recurso não encontrado.
- `CONFLICT`: conflito de unicidade ou regra de negócio.
- `DATABASE_ERROR`: erro de banco não esperado.
- `INTERNAL_ERROR`: erro não classificado.

## GET /health

Verifica se a aplicação está disponível.

Resposta `200`:

```json
{
  "status": "ok"
}
```

Durante desenvolvimento, campos extras como linguagem e versão podem existir somente se forem padronizados. Na coleta principal, a resposta deve ser equivalente entre linguagens.

## GET /customers/{id}

Busca um cliente por identificador.

Parâmetros:

- `id`: inteiro positivo.

Resposta `200`:

```json
{
  "id": 1,
  "fullName": "Cliente Base 0001",
  "email": "cliente.base.0001@example.com",
  "documentNumber": "10000000001",
  "phone": "+55 11 900000001",
  "status": "active",
  "address": {
    "id": 1,
    "label": "main",
    "street": "Rua Experimental 1",
    "number": "101",
    "complement": null,
    "district": "Bairro 1",
    "city": "Sao Paulo",
    "state": "SP",
    "postalCode": "01000001",
    "isDefault": true
  },
  "createdAt": "2026-01-01T08:01:00Z",
  "updatedAt": "2026-01-01T08:01:00Z"
}
```

Erros:

- `400 VALIDATION_ERROR` quando `id` não for inteiro positivo.
- `404 NOT_FOUND` quando o cliente não existir.

## GET /customers

Consulta paginada de clientes.

Query string:

- `page`: inteiro positivo, padrão `1`.
- `pageSize`: inteiro entre `1` e `100`, padrão `50`.

Resposta `200`:

```json
{
  "page": 1,
  "pageSize": 50,
  "total": 200,
  "items": []
}
```

Erros:

- `400 VALIDATION_ERROR` para paginação inválida.

## POST /customers

Cria cliente com endereço associado e registro em `audit_logs`.

Payload:

```json
{
  "fullName": "Cliente Carga 0001",
  "email": "cliente.carga.0001@example.com",
  "documentNumber": "90000000001",
  "phone": "+55 11 980000001",
  "address": {
    "label": "main",
    "street": "Rua Carga 1",
    "number": "501",
    "complement": null,
    "district": "Bairro Carga 2",
    "city": "Sao Paulo",
    "state": "SP",
    "postalCode": "02000001",
    "isDefault": true
  }
}
```

Resposta `201`: mesmo formato de `GET /customers/{id}`.

Erros:

- `400 VALIDATION_ERROR` para campos obrigatórios ausentes ou inválidos.
- `409 CONFLICT` para email ou documento duplicado.

## PUT /customers/{id}

Atualiza cliente existente e endereço principal.

Payload:

```json
{
  "fullName": "Cliente Atualizado 0001",
  "phone": "+55 11 970000001",
  "status": "active",
  "address": {
    "label": "main",
    "street": "Rua Atualizada 1",
    "number": "901",
    "complement": null,
    "district": "Bairro Atualizado 2",
    "city": "Sao Paulo",
    "state": "SP",
    "postalCode": "03000001",
    "isDefault": true
  }
}
```

Resposta `200`: mesmo formato de `GET /customers/{id}`.

Erros:

- `400 VALIDATION_ERROR` para `id` ou payload inválido.
- `404 NOT_FOUND` para cliente inexistente.

## GET /products

Busca produtos por categoria.

Query string:

- `categoryId`: inteiro positivo obrigatório.

Resposta `200`:

```json
{
  "categoryId": 1,
  "items": [
    {
      "id": 1,
      "categoryId": 1,
      "sku": "SKU-00001",
      "name": "Produto Base 0001",
      "unitPrice": "11.11",
      "stockQuantity": 1001,
      "active": true
    }
  ]
}
```

Erros:

- `400 VALIDATION_ERROR` para categoria inválida.
- `404 NOT_FOUND` se a categoria não existir.

## POST /orders

Cria pedido com itens, pagamento, baixa de estoque e `audit_logs`. O endpoint deve usar transação obrigatoriamente.

Payload:

```json
{
  "customerId": 1,
  "addressId": 1,
  "items": [
    {
      "productId": 49,
      "quantity": 2
    }
  ],
  "payment": {
    "method": "debit_card"
  }
}
```

Resposta `201`: mesmo formato de `GET /orders/{id}`.

Erros:

- `400 VALIDATION_ERROR` para payload inválido.
- `404 NOT_FOUND` para cliente, endereço ou produto inexistente.
- `409 CONFLICT` para estoque insuficiente.

## GET /orders/{id}

Busca pedido completo com joins entre `orders`, `customers`, `addresses`, `order_items`, `products`, `categories` e `payments`.

Resposta `200`:

```json
{
  "id": 1,
  "status": "paid",
  "totalAmount": "78.12",
  "customer": {},
  "address": {},
  "items": [],
  "payment": {},
  "createdAt": "2026-01-02T10:01:00Z",
  "updatedAt": "2026-01-02T10:01:00Z"
}
```

Erros:

- `400 VALIDATION_ERROR` quando `id` não for inteiro positivo.
- `404 NOT_FOUND` quando o pedido não existir.

## Exemplos inválidos

Cliente sem email:

```json
{
  "fullName": "Cliente Sem Email",
  "documentNumber": "123",
  "address": {}
}
```

Pedido sem itens:

```json
{
  "customerId": 1,
  "addressId": 1,
  "items": [],
  "payment": {
    "method": "pix"
  }
}
```
