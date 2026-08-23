# Contrato canonico das APIs

Este e o contrato operacional comum das implementacoes Python, Node.js, Java,
Go e .NET. O TCC define os oito endpoints, o PostgreSQL compartilhado, SQL direto
e equivalencia funcional; este documento fixa os detalhes de campos que o texto
academico nao especifica.

## Regras comuns

- Toda resposta, inclusive erros de rota, metodo, validacao, banco e internos,
  usa `application/json` e nao termina com quebra de linha.
- Campos JSON usam `camelCase`. Propriedades desconhecidas sao ignoradas e nao
  sao persistidas no `audit_logs`.
- Corpo vazio, JSON truncado e constantes nao permitidas pelo JSON, como `NaN`
  e `Infinity`, geram `Invalid JSON`. `null`, arrays e escalares JSON validos
  geram `Must be a JSON object`.
- Strings validas sao normalizadas removendo espacos das extremidades. Strings
  obrigatorias ausentes, nulas, de outro tipo, vazias ou apenas com espacos geram
  `Required non-empty string`.
- `phone` e `address.complement` sao opcionais. Ausencia ou `null` produz `null`;
  string e normalizada; outro tipo gera `Must be a string or null`.
- IDs e quantidades no JSON sao numeros integrais positivos de `1` a
  `2147483647`. `1` e `1.0` sao aceitos. Strings numericas, booleanos, fracoes,
  zero, negativos e valores fora da faixa sao rejeitados.
- IDs em path e query aceitam somente digitos ASCII e a mesma faixa de 32 bits.
- Datas usam UTC em `YYYY-MM-DDTHH:MM:SSZ`, sem fracao. Valores monetarios sao
  strings com duas casas, por exemplo `"11.10"`.
- Erros de validacao acumulam detalhes na ordem documentada. Campos aninhados
  usam `address.street`, `items[0].quantity` e `payment.method`.
- Cliente sem endereco padrao usa `"address": null` na consulta individual e na
  lista.
- Toda transacao e revertida em qualquer erro ocorrido depois de seu inicio.

## Contrato de erro

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request payload",
    "details": [
      {"field": "email", "message": "Required non-empty string"}
    ]
  }
}
```

| Situacao | HTTP | `error.code` | `error.message` | `error.details` |
|---|---:|---|---|---|
| Payload invalido | 400 | `VALIDATION_ERROR` | `Invalid request payload` | Lista ordenada de campos |
| Path ou query invalido | 400 | `VALIDATION_ERROR` | `Invalid request parameter` | Um campo |
| Entidade inexistente | 404 | `NOT_FOUND` | Mensagem especifica | `[]` |
| Rota inexistente | 404 | `NOT_FOUND` | `Route not found` | `[]` |
| Metodo incompatível | 405 | `METHOD_NOT_ALLOWED` | `Method not allowed` | `[]` |
| Email/documento duplicado | 409 | `CONFLICT` | `Customer email or document already exists` | `[]` |
| Estoque insuficiente | 409 | `CONFLICT` | `Insufficient stock` | `[]` |
| Falha inesperada do PostgreSQL/driver | 500 | `DATABASE_ERROR` | `Database error` | `[]` |
| Falha interna nao relacionada ao banco | 500 | `INTERNAL_ERROR` | `Internal server error` | `[]` |

Mensagens de excecao, SQLSTATE, stack trace, HTML e formatos nativos dos
frameworks nunca sao expostos.

## Objetos de resposta

### `Address`

```json
{
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
}
```

### `Customer`

```json
{
  "id": 1,
  "fullName": "Cliente Base 0001",
  "email": "cliente.base.0001@example.com",
  "documentNumber": "10000000001",
  "phone": null,
  "status": "active",
  "address": null,
  "createdAt": "2026-01-01T08:01:00Z",
  "updatedAt": "2026-01-01T08:01:00Z"
}
```

`phone` e `address` podem ser `null`. Quando presente, `address` tem a estrutura
completa de `Address`.

### `Product`

```json
{
  "id": 1,
  "categoryId": 1,
  "sku": "SKU-00001",
  "name": "Produto Base 0001",
  "unitPrice": "11.11",
  "stockQuantity": 1001,
  "active": true
}
```

### `Order`

```json
{
  "id": 1,
  "status": "paid",
  "totalAmount": "78.12",
  "customer": {
    "id": 1,
    "fullName": "Cliente Base 0001",
    "email": "cliente.base.0001@example.com",
    "documentNumber": "10000000001",
    "phone": null,
    "status": "active",
    "address": {
      "id": 1, "label": "main", "street": "Rua Experimental 1",
      "number": "101", "complement": null, "district": "Bairro 1",
      "city": "Sao Paulo", "state": "SP", "postalCode": "01000001",
      "isDefault": true
    },
    "createdAt": "2026-01-01T08:01:00Z",
    "updatedAt": "2026-01-01T08:01:00Z"
  },
  "address": {
    "id": 1, "label": "main", "street": "Rua Experimental 1",
    "number": "101", "complement": null, "district": "Bairro 1",
    "city": "Sao Paulo", "state": "SP", "postalCode": "01000001",
    "isDefault": true
  },
  "items": [
    {
      "id": 1,
      "quantity": 2,
      "unitPrice": "39.06",
      "totalPrice": "78.12",
      "product": {
        "id": 49, "categoryId": 4, "categoryName": "Office",
        "sku": "SKU-00049", "name": "Produto Base 0049",
        "unitPrice": "39.06", "stockQuantity": 100047, "active": true
      }
    }
  ],
  "payment": {
    "id": 1,
    "method": "debit_card",
    "status": "paid",
    "amount": "78.12",
    "paidAt": "2026-01-02T10:04:00Z"
  },
  "createdAt": "2026-01-02T10:01:00Z",
  "updatedAt": "2026-01-02T10:01:00Z"
}
```

## Matriz dos endpoints

| Metodo e rota | Parametros | Payload | Sucesso | Erros especificos | SQL/transacao | Efeito no banco |
|---|---|---|---|---|---|---|
| `GET /health` | Nenhum | Nenhum | `200`, `{"status":"ok"}` | Erros comuns de rota/metodo | Nenhum | Nenhum |
| `GET /customers/{id}` | `id` | Nenhum | `200 Customer` | `400`; `404 Customer not found` | Cliente + endereco padrao | Nenhum |
| `GET /customers` | `page=1`, `pageSize=50` | Nenhum | `200` pagina | `400` | `COUNT` + lista com endereco | Nenhum |
| `POST /customers` | Nenhum | `CreateCustomer` | `201 Customer` | `400`; `409` duplicidade | Transacao de cliente, endereco, auditoria e releitura | Cria 3 linhas |
| `PUT /customers/{id}` | `id` | `UpdateCustomer` | `200 Customer` | `400`; `404` | Transacao de cliente, endereco, auditoria e releitura | Atualiza/cria 3 linhas |
| `GET /products` | `categoryId` | Nenhum | `200` lista | `400`; `404 Category not found` | Verifica categoria + lista ativos | Nenhum |
| `POST /orders` | Nenhum | `CreateOrder` | `201 Order` | `400`; `404`; `409` estoque | Uma transacao com locks, estoque, itens, total, pagamento e auditoria | Cria pedido e baixa estoque |
| `GET /orders/{id}` | `id` | Nenhum | `200 Order` | `400`; `404 Order not found` | Consulta completa com sete joins | Nenhum |

## `GET /health`

Nao recebe parametros nem payload e nao consulta o banco. Retorna `200` com
`{"status":"ok"}`.

## `GET /customers/{id}`

- `id`: inteiro positivo ASCII de 32 bits.
- Sucesso: `200 Customer`.
- Erros: `400` para id invalido; `404 NOT_FOUND`, `Customer not found`.
- SQL: seleciona `customers` e faz `LEFT JOIN addresses` por `customer_id` e
  `is_default = true`.
- Transacao/efeito: nenhuma escrita.

## `GET /customers`

- `page`: opcional, padrao `1`; `pageSize`: opcional, padrao `50`, faixa `1..100`.
- Sucesso: `200` com `page`, `pageSize`, `total` e `items: Customer[]`.
- Erros: `400`; `pageSize > 100` gera `Must be between 1 and 100`.
- SQL: `count(*)`; consulta com o mesmo `LEFT JOIN` do endpoint individual,
  ordenada por `customers.created_at, customers.id`, com `LIMIT/OFFSET`.
- Transacao/efeito: nenhuma escrita.

## `POST /customers`

| Campo | Regra |
|---|---|
| `fullName` | String obrigatoria e normalizada |
| `email` | String obrigatoria, normalizada e contendo `@` |
| `documentNumber` | String obrigatoria e normalizada |
| `phone` | String opcional ou `null` |
| `address` | Objeto obrigatorio |
| `address.label` | String obrigatoria |
| `address.street` | String obrigatoria |
| `address.number` | String obrigatoria |
| `address.complement` | String opcional ou `null` |
| `address.district` | String obrigatoria |
| `address.city` | String obrigatoria |
| `address.state` | String obrigatoria com 2 letras ASCII; normalizada para maiusculas |
| `address.postalCode` | String obrigatoria |
| `address.isDefault` | Booleano obrigatorio |

- Sucesso: `201 Customer`.
- Erros: `400`; `409 CONFLICT` para email ou documento ja existente.
- Transacao: `INSERT customers RETURNING id`; `INSERT addresses`; `INSERT
  audit_logs`; releitura; `COMMIT`.
- Auditoria: `entity_type=customer`, `action=create_customer`, payload normalizado
  com as chaves `camelCase` de `CreateCustomer`.
- Efeito: cria uma linha em `customers`, `addresses` e `audit_logs`.

## `PUT /customers/{id}`

- `id`: inteiro positivo ASCII de 32 bits.
- Payload: `fullName` obrigatorio; `phone` opcional ou `null`; `status` obrigatorio
  e restrito a `active|inactive`; `address` completo com as regras anteriores.
- Sucesso: `200 Customer`; erros: `400` ou `404 Customer not found`.
- Transacao: atualiza cliente; atualiza o endereco padrao ou insere um quando nao
  existe; insere auditoria; rele o cliente; `COMMIT`.
- Auditoria: `entity_type=customer`, `action=update_customer`, payload normalizado
  em `camelCase`.
- Efeito: altera `customers`, altera ou cria `addresses` e cria `audit_logs`.

## `GET /products`

- `categoryId`: obrigatorio, inteiro positivo ASCII de 32 bits.
- Sucesso: `200` com `categoryId` e `items: Product[]`.
- Erros: `400`; `404 NOT_FOUND`, `Category not found`.
- SQL: verifica a categoria; lista produtos ativos da categoria ordenados por id.
- Transacao/efeito: nenhuma escrita.

## `POST /orders`

| Campo | Regra |
|---|---|
| `customerId` | Numero integral positivo de 32 bits |
| `addressId` | Numero integral positivo de 32 bits |
| `items` | Array obrigatorio com ao menos um elemento |
| `items[i]` | Objeto; outro tipo gera `Must be an object` |
| `items[i].productId` | Numero integral positivo de 32 bits |
| `items[i].quantity` | Numero integral positivo de 32 bits |
| `payment` | Objeto obrigatorio |
| `payment.method` | `credit_card`, `debit_card`, `pix` ou `boleto` |

- Ausencia de `payment.method` usa o campo de erro `payment.method`, nunca apenas
  `method`.
- Sucesso: `201 Order`.
- Erros: `400`; `404` com `Customer not found`, `Address not found` ou `Product
  not found`; `409 CONFLICT`, `Insufficient stock`.
- Transacao unica: valida cliente ativo e endereco; cria pedido; para cada item
  seleciona produto ativo com `FOR UPDATE`, valida e reduz estoque
  condicionalmente, cria item; calcula total; marca pedido `paid`; cria pagamento
  `paid`; cria auditoria; rele pedido; `COMMIT`.
- Auditoria: `entity_type=order`, `action=create_order`, payload normalizado em
  `camelCase`.
- Efeito: cria `orders`, `order_items`, `payments`, `audit_logs` e reduz estoque.
  Qualquer falha reverte todos os efeitos.

## `GET /orders/{id}`

- `id`: inteiro positivo ASCII de 32 bits.
- Sucesso: `200 Order` completo.
- Erros: `400`; `404 NOT_FOUND`, `Order not found`.
- SQL: une `orders`, `customers`, `addresses`, `order_items`, `products`,
  `categories` e `payments`, seleciona todos os campos da resposta e ordena por
  `order_items.id`.
- Transacao/efeito: nenhuma escrita.

## Rotas e metodos

- Caminho sem rota: `404 NOT_FOUND`, `Route not found`, `details: []`.
- Metodo diferente do registrado em um caminho existente: `405
  METHOD_NOT_ALLOWED`, `Method not allowed`, `details: []`.
- Rota e metodo sao resolvidos antes do corpo. Portanto, um corpo invalido nao
  substitui o `404` de uma rota inexistente nem o `405` de um metodo incompatível.
- Caminho de entidade com id sintaticamente invalido, como `/customers/abc`,
  pertence a rota e retorna o `400` de parametro.
