#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

BASE_URL="${1:-$API_BASE_URL}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

first_line() {
  head -n 1 "$1" | tr -d '\r\n'
}

request() {
  local name="$1"
  local expected="$2"
  shift 2
  local output="$TMP_DIR/response.json"
  local error="$TMP_DIR/error.txt"
  local status
  local exit_code

  set +e
  status=$(curl -sS -o "$output" -w "%{http_code}" "$@" 2>"$error")
  exit_code=$?
  set -e

  if [ "$exit_code" -ne 0 ]; then
    echo "[ERRO] $name falhou ao chamar curl"
    cat "$error"
    return 1
  fi

  echo "[$status] $name"
  if [ "$status" != "$expected" ]; then
    echo "Esperado HTTP $expected, recebido HTTP $status"
    cat "$output"
    return 1
  fi
}

CUSTOMER_ID="$(first_line common/payloads/ids_customers.jsonl)"
CATEGORY_ID="$(first_line common/payloads/ids_categories.jsonl)"
ORDER_ID="$(first_line common/payloads/ids_orders.jsonl)"

head -n 1 common/payloads/customers_create.jsonl > "$TMP_DIR/customer_create.json"
head -n 1 common/payloads/customers_update.jsonl > "$TMP_DIR/customer_update.json"
head -n 1 common/payloads/orders_create.jsonl > "$TMP_DIR/order_create.json"

request "GET /health" 200 "$BASE_URL/health"
request "GET /customers/{id}" 200 "$BASE_URL/customers/$CUSTOMER_ID"
request "GET /customers?page=1&pageSize=50" 200 "$BASE_URL/customers?page=1&pageSize=50"
request "POST /customers" 201 -X POST "$BASE_URL/customers" -H "Content-Type: application/json" --data @"$TMP_DIR/customer_create.json"
request "PUT /customers/{id}" 200 -X PUT "$BASE_URL/customers/$CUSTOMER_ID" -H "Content-Type: application/json" --data @"$TMP_DIR/customer_update.json"
request "GET /products?categoryId={id}" 200 "$BASE_URL/products?categoryId=$CATEGORY_ID"
request "POST /orders" 201 -X POST "$BASE_URL/orders" -H "Content-Type: application/json" --data @"$TMP_DIR/order_create.json"
request "GET /orders/{id}" 200 "$BASE_URL/orders/$ORDER_ID"

echo "Validacao manual de payloads concluida com sucesso."
