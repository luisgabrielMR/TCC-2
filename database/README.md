# Banco de dados

O experimento usa um único PostgreSQL para todas as APIs. Antes de cada etapa
importante, o banco é restaurado para uma base conhecida. Assim, uma linguagem
não recebe dados deixados pela anterior.

O banco possui clientes, endereços, categorias, produtos, pedidos, itens,
pagamentos e auditoria. O conjunto inicial tem 200 mil clientes, endereços,
pedidos e pagamentos; 400 mil itens de pedido e registros de auditoria; 100
produtos em cinco categorias.

Os atalhos do menu Windows preparam, validam e restauram o banco. Para quem usa
terminal, os scripts principais são:

```bash
./scripts/setup_database.sh
./scripts/validate_database.sh
./scripts/reset_db.sh
```

O reset recupera dados e sequências, mas não transforma o computador em um
ambiente de cache frio. Veja como isso é feito em [TECHNICAL.md](TECHNICAL.md).
