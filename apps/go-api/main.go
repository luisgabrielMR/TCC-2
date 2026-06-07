package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/lib/pq"
)

type settings struct {
	databaseURL    string
	port           string
	poolMin        int
	poolMax        int
	acquireTimeout int
	idleTimeout    int
	maxLifetime    int
}

type apiError struct {
	Status  int
	Code    string
	Message string
	Details []map[string]string
}

func (e apiError) Error() string {
	return e.Message
}

type addressInput struct {
	Label      string  `json:"label"`
	Street     string  `json:"street"`
	Number     string  `json:"number"`
	Complement *string `json:"complement"`
	District   string  `json:"district"`
	City       string  `json:"city"`
	State      string  `json:"state"`
	PostalCode string  `json:"postalCode"`
	IsDefault  bool    `json:"isDefault"`
}

type createCustomerRequest struct {
	FullName       string       `json:"fullName"`
	Email          string       `json:"email"`
	DocumentNumber string       `json:"documentNumber"`
	Phone          *string      `json:"phone"`
	Address        addressInput `json:"address"`
}

type updateCustomerRequest struct {
	FullName string       `json:"fullName"`
	Phone    *string      `json:"phone"`
	Status   string       `json:"status"`
	Address  addressInput `json:"address"`
}

type orderItemInput struct {
	ProductID int `json:"productId"`
	Quantity  int `json:"quantity"`
}

type createOrderRequest struct {
	CustomerID int `json:"customerId"`
	AddressID  int `json:"addressId"`
	Items      []orderItemInput `json:"items"`
	Payment    struct {
		Method string `json:"method"`
	} `json:"payment"`
}

type customerRow struct {
	ID             int64
	FullName       string
	Email          string
	DocumentNumber string
	Phone          sql.NullString
	Status         string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	AddressID      sql.NullInt64
	Label          sql.NullString
	Street         sql.NullString
	Number         sql.NullString
	Complement     sql.NullString
	District       sql.NullString
	City           sql.NullString
	State          sql.NullString
	PostalCode     sql.NullString
	IsDefault      sql.NullBool
}

type app struct {
	db       *sql.DB
	settings settings
}

func main() {
	cfg := loadSettings()
	db, err := sql.Open("postgres", cfg.databaseURL)
	if err != nil {
		log.Fatal(err)
	}
	db.SetMaxOpenConns(cfg.poolMax)
	db.SetMaxIdleConns(cfg.poolMin)
	db.SetConnMaxIdleTime(time.Duration(cfg.idleTimeout) * time.Second)
	db.SetConnMaxLifetime(time.Duration(cfg.maxLifetime) * time.Second)

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.acquireTimeout)*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		log.Fatal(err)
	}

	application := &app{db: db, settings: cfg}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", application.health)
	mux.HandleFunc("/customers", application.customers)
	mux.HandleFunc("/customers/", application.customerByID)
	mux.HandleFunc("/products", application.products)
	mux.HandleFunc("/orders", application.orders)
	mux.HandleFunc("/orders/", application.orderByID)

	server := &http.Server{
		Addr:              "0.0.0.0:" + cfg.port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("Go API listening on %s", cfg.port)
	log.Fatal(server.ListenAndServe())
}

func loadSettings() settings {
	host := env("POSTGRES_HOST", "localhost")
	port := env("POSTGRES_PORT", "5432")
	db := env("POSTGRES_DB", "benchmark_db")
	user := env("POSTGRES_USER", "benchmark_user")
	password := env("POSTGRES_PASSWORD", "benchmark_password")
	databaseURL := env("DATABASE_URL", fmt.Sprintf("postgresql://%s:%s@%s:%s/%s?sslmode=disable", user, password, host, port, db))
	return settings{
		databaseURL:    databaseURL,
		port:           env("PORT", "8000"),
		poolMin:        intEnv("DB_POOL_MIN", 1),
		poolMax:        intEnv("DB_POOL_MAX", 20),
		acquireTimeout: intEnv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10),
		idleTimeout:    intEnv("DB_POOL_IDLE_TIMEOUT_SECONDS", 60),
		maxLifetime:    intEnv("DB_POOL_MAX_LIFETIME_SECONDS", 300),
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func (a *app) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *app) customers(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		a.listCustomers(w, r)
	case http.MethodPost:
		a.createCustomer(w, r)
	default:
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
	}
}

func (a *app) customerByID(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r.URL.Path, "/customers/")
	if err != nil {
		writeError(w, err)
		return
	}
	switch r.Method {
	case http.MethodGet:
		a.getCustomer(w, r, id)
	case http.MethodPut:
		a.updateCustomer(w, r, id)
	default:
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
	}
}

func (a *app) products(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
	categoryID, err := positiveInt(r.URL.Query().Get("categoryId"), "categoryId")
	if err != nil {
		writeError(w, err)
		return
	}
	var existingCategory int
	if err := a.db.QueryRowContext(r.Context(), "SELECT id FROM categories WHERE id = $1", categoryID).Scan(&existingCategory); err != nil {
		writeError(w, notFoundOrDB(err, "Category not found"))
		return
	}
	rows, err := a.db.QueryContext(r.Context(), listProductsSQL, categoryID)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, catID, stock int64
		var sku, name, price string
		var active bool
		if err := rows.Scan(&id, &catID, &sku, &name, &price, &stock, &active); err != nil {
			writeError(w, dbError(err))
			return
		}
		items = append(items, map[string]any{
			"id": id, "categoryId": catID, "sku": sku, "name": name,
			"unitPrice": price, "stockQuantity": stock, "active": active,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"categoryId": categoryID, "items": items})
}

func (a *app) orders(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
	a.createOrder(w, r)
}

func (a *app) orderByID(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r.URL.Path, "/orders/")
	if err != nil {
		writeError(w, err)
		return
	}
	if r.Method != http.MethodGet {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
	order, err := a.fetchOrder(r.Context(), a.db, id)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, order)
}

func (a *app) getCustomer(w http.ResponseWriter, r *http.Request, id int) {
	customer, err := a.fetchCustomer(r.Context(), a.db, id)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, customer)
}

func (a *app) listCustomers(w http.ResponseWriter, r *http.Request) {
	page, pageSize, err := pagination(r)
	if err != nil {
		writeError(w, err)
		return
	}
	offset := (page - 1) * pageSize
	var total int
	if err := a.db.QueryRowContext(r.Context(), "SELECT count(*)::int FROM customers").Scan(&total); err != nil {
		writeError(w, dbError(err))
		return
	}
	rows, err := a.db.QueryContext(r.Context(), listCustomersSQL, pageSize, offset)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		row, err := scanCustomer(rows)
		if err != nil {
			writeError(w, dbError(err))
			return
		}
		items = append(items, customerJSON(row))
	}
	writeJSON(w, http.StatusOK, map[string]any{"page": page, "pageSize": pageSize, "total": total, "items": items})
}

func (a *app) createCustomer(w http.ResponseWriter, r *http.Request) {
	var payload createCustomerRequest
	if err := decodeJSON(r, &payload); err != nil {
		writeError(w, err)
		return
	}
	if err := validateCreateCustomer(payload); err != nil {
		writeError(w, err)
		return
	}
	tx, err := a.db.BeginTx(r.Context(), nil)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	defer tx.Rollback()

	var customerID int
	err = tx.QueryRowContext(r.Context(), insertCustomerSQL, payload.FullName, payload.Email, payload.DocumentNumber, payload.Phone).Scan(&customerID)
	if err != nil {
		if pgErr, ok := err.(*pq.Error); ok && string(pgErr.Code) == "23505" {
			writeError(w, apiError{Status: 409, Code: "CONFLICT", Message: "Customer email or document already exists"})
			return
		}
		writeError(w, dbError(err))
		return
	}
	if _, err := tx.ExecContext(r.Context(), insertAddressSQL, customerID, payload.Address.Label, payload.Address.Street, payload.Address.Number, payload.Address.Complement, payload.Address.District, payload.Address.City, payload.Address.State, payload.Address.PostalCode, payload.Address.IsDefault); err != nil {
		writeError(w, dbError(err))
		return
	}
	audit, _ := json.Marshal(payload)
	if _, err := tx.ExecContext(r.Context(), insertAuditSQL, "customer", customerID, "create_customer", string(audit)); err != nil {
		writeError(w, dbError(err))
		return
	}
	customer, err := a.fetchCustomer(r.Context(), tx, customerID)
	if err != nil {
		writeError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		writeError(w, dbError(err))
		return
	}
	writeJSON(w, http.StatusCreated, customer)
}

func (a *app) updateCustomer(w http.ResponseWriter, r *http.Request, id int) {
	var payload updateCustomerRequest
	if err := decodeJSON(r, &payload); err != nil {
		writeError(w, err)
		return
	}
	if err := validateUpdateCustomer(payload); err != nil {
		writeError(w, err)
		return
	}
	tx, err := a.db.BeginTx(r.Context(), nil)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	defer tx.Rollback()
	res, err := tx.ExecContext(r.Context(), updateCustomerSQL, payload.FullName, payload.Phone, payload.Status, id)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	count, _ := res.RowsAffected()
	if count == 0 {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Customer not found"})
		return
	}
	if _, err := tx.ExecContext(r.Context(), updateAddressSQL, payload.Address.Label, payload.Address.Street, payload.Address.Number, payload.Address.Complement, payload.Address.District, payload.Address.City, payload.Address.State, payload.Address.PostalCode, payload.Address.IsDefault, id); err != nil {
		writeError(w, dbError(err))
		return
	}
	audit, _ := json.Marshal(payload)
	if _, err := tx.ExecContext(r.Context(), insertAuditSQL, "customer", id, "update_customer", string(audit)); err != nil {
		writeError(w, dbError(err))
		return
	}
	customer, err := a.fetchCustomer(r.Context(), tx, id)
	if err != nil {
		writeError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		writeError(w, dbError(err))
		return
	}
	writeJSON(w, http.StatusOK, customer)
}

func (a *app) createOrder(w http.ResponseWriter, r *http.Request) {
	var payload createOrderRequest
	if err := decodeJSON(r, &payload); err != nil {
		writeError(w, err)
		return
	}
	if err := validateCreateOrder(payload); err != nil {
		writeError(w, err)
		return
	}
	tx, err := a.db.BeginTx(r.Context(), nil)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	defer tx.Rollback()
	var exists int
	if err := tx.QueryRowContext(r.Context(), "SELECT id FROM customers WHERE id = $1 AND status = 'active'", payload.CustomerID).Scan(&exists); err != nil {
		writeError(w, notFoundOrDB(err, "Customer not found"))
		return
	}
	if err := tx.QueryRowContext(r.Context(), "SELECT id FROM addresses WHERE id = $1 AND customer_id = $2", payload.AddressID, payload.CustomerID).Scan(&exists); err != nil {
		writeError(w, notFoundOrDB(err, "Address not found"))
		return
	}
	var orderID int
	if err := tx.QueryRowContext(r.Context(), "INSERT INTO orders (customer_id, address_id, status, total_amount) VALUES ($1, $2, 'created', 0) RETURNING id", payload.CustomerID, payload.AddressID).Scan(&orderID); err != nil {
		writeError(w, dbError(err))
		return
	}
	for _, item := range payload.Items {
		var productID, stock int
		var price string
		if err := tx.QueryRowContext(r.Context(), "SELECT id, unit_price::text, stock_quantity FROM products WHERE id = $1 AND active = true FOR UPDATE", item.ProductID).Scan(&productID, &price, &stock); err != nil {
			writeError(w, notFoundOrDB(err, "Product not found"))
			return
		}
		if stock < item.Quantity {
			writeError(w, apiError{Status: 409, Code: "CONFLICT", Message: "Insufficient stock"})
			return
		}
		res, err := tx.ExecContext(r.Context(), "UPDATE products SET stock_quantity = stock_quantity - $1 WHERE id = $2 AND stock_quantity >= $3", item.Quantity, item.ProductID, item.Quantity)
		if err != nil {
			writeError(w, dbError(err))
			return
		}
		count, _ := res.RowsAffected()
		if count == 0 {
			writeError(w, apiError{Status: 409, Code: "CONFLICT", Message: "Insufficient stock"})
			return
		}
		if _, err := tx.ExecContext(r.Context(), "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)", orderID, item.ProductID, item.Quantity, price); err != nil {
			writeError(w, dbError(err))
			return
		}
	}
	var total string
	if err := tx.QueryRowContext(r.Context(), "UPDATE orders SET total_amount = (SELECT sum(total_price)::numeric(12, 2) FROM order_items WHERE order_id = $1), status = 'paid', updated_at = now() WHERE id = $2 RETURNING total_amount::text", orderID, orderID).Scan(&total); err != nil {
		writeError(w, dbError(err))
		return
	}
	if _, err := tx.ExecContext(r.Context(), "INSERT INTO payments (order_id, method, status, amount, paid_at) VALUES ($1, $2, 'paid', $3, now())", orderID, payload.Payment.Method, total); err != nil {
		writeError(w, dbError(err))
		return
	}
	audit, _ := json.Marshal(payload)
	if _, err := tx.ExecContext(r.Context(), insertAuditSQL, "order", orderID, "create_order", string(audit)); err != nil {
		writeError(w, dbError(err))
		return
	}
	order, err := a.fetchOrder(r.Context(), tx, orderID)
	if err != nil {
		writeError(w, err)
		return
	}
	if err := tx.Commit(); err != nil {
		writeError(w, dbError(err))
		return
	}
	writeJSON(w, http.StatusCreated, order)
}

type queryer interface {
	QueryRowContext(context.Context, string, ...any) *sql.Row
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}

func (a *app) fetchCustomer(ctx context.Context, q queryer, id int) (map[string]any, error) {
	rows, err := q.QueryContext(ctx, getCustomerSQL, id)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	if !rows.Next() {
		return nil, apiError{Status: 404, Code: "NOT_FOUND", Message: "Customer not found"}
	}
	row, err := scanCustomer(rows)
	if err != nil {
		return nil, dbError(err)
	}
	return customerJSON(row), nil
}

func (a *app) fetchOrder(ctx context.Context, q queryer, id int) (map[string]any, error) {
	rows, err := q.QueryContext(ctx, getOrderSQL, id)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	var first map[string]any
	items := []map[string]any{}
	for rows.Next() {
		var r orderRow
		if err := rows.Scan(&r.OrderID, &r.OrderStatus, &r.TotalAmount, &r.OrderCreatedAt, &r.OrderUpdatedAt, &r.CustomerID, &r.FullName, &r.Email, &r.DocumentNumber, &r.Phone, &r.CustomerStatus, &r.CustomerCreatedAt, &r.CustomerUpdatedAt, &r.AddressID, &r.Label, &r.Street, &r.Number, &r.Complement, &r.District, &r.City, &r.State, &r.PostalCode, &r.IsDefault, &r.ItemID, &r.Quantity, &r.ItemUnitPrice, &r.ItemTotalPrice, &r.ProductID, &r.SKU, &r.ProductName, &r.ProductUnitPrice, &r.StockQuantity, &r.Active, &r.CategoryID, &r.CategoryName, &r.PaymentID, &r.PaymentMethod, &r.PaymentStatus, &r.PaymentAmount, &r.PaidAt); err != nil {
			return nil, dbError(err)
		}
		if first == nil {
			first = orderBaseJSON(r)
		}
		items = append(items, itemJSON(r))
	}
	if first == nil {
		return nil, apiError{Status: 404, Code: "NOT_FOUND", Message: "Order not found"}
	}
	first["items"] = items
	return first, nil
}

type orderRow struct {
	OrderID, CustomerID, AddressID, ItemID, Quantity, ProductID, StockQuantity, CategoryID, PaymentID int64
	OrderStatus, TotalAmount, FullName, Email, DocumentNumber, CustomerStatus string
	Label, Street, Number, Complement, District, City, State, PostalCode sql.NullString
	ItemUnitPrice, ItemTotalPrice, SKU, ProductName, ProductUnitPrice, CategoryName string
	PaymentMethod, PaymentStatus, PaymentAmount string
	Active, IsDefault bool
	Phone sql.NullString
	OrderCreatedAt, OrderUpdatedAt, CustomerCreatedAt, CustomerUpdatedAt, PaidAt time.Time
}

func scanCustomer(rows *sql.Rows) (customerRow, error) {
	var row customerRow
	err := rows.Scan(&row.ID, &row.FullName, &row.Email, &row.DocumentNumber, &row.Phone, &row.Status, &row.CreatedAt, &row.UpdatedAt, &row.AddressID, &row.Label, &row.Street, &row.Number, &row.Complement, &row.District, &row.City, &row.State, &row.PostalCode, &row.IsDefault)
	return row, err
}

func customerJSON(row customerRow) map[string]any {
	return map[string]any{
		"id": row.ID, "fullName": row.FullName, "email": row.Email, "documentNumber": row.DocumentNumber,
		"phone": nullableString(row.Phone), "status": row.Status, "address": addressJSON(row),
		"createdAt": row.CreatedAt.UTC().Format(time.RFC3339), "updatedAt": row.UpdatedAt.UTC().Format(time.RFC3339),
	}
}

func addressJSON(row customerRow) map[string]any {
	if !row.AddressID.Valid {
		return nil
	}
	return map[string]any{
		"id": row.AddressID.Int64, "label": row.Label.String, "street": row.Street.String, "number": row.Number.String,
		"complement": nullableString(row.Complement), "district": row.District.String, "city": row.City.String,
		"state": row.State.String, "postalCode": row.PostalCode.String, "isDefault": row.IsDefault.Bool,
	}
}

func orderBaseJSON(r orderRow) map[string]any {
	addr := map[string]any{"id": r.AddressID, "label": r.Label.String, "street": r.Street.String, "number": r.Number.String, "complement": nullableString(r.Complement), "district": r.District.String, "city": r.City.String, "state": r.State.String, "postalCode": r.PostalCode.String, "isDefault": r.IsDefault}
	return map[string]any{
		"id": r.OrderID, "status": r.OrderStatus, "totalAmount": r.TotalAmount,
		"customer": map[string]any{"id": r.CustomerID, "fullName": r.FullName, "email": r.Email, "documentNumber": r.DocumentNumber, "phone": nullableString(r.Phone), "status": r.CustomerStatus, "address": addr, "createdAt": r.CustomerCreatedAt.UTC().Format(time.RFC3339), "updatedAt": r.CustomerUpdatedAt.UTC().Format(time.RFC3339)},
		"address": addr,
		"payment": map[string]any{"id": r.PaymentID, "method": r.PaymentMethod, "status": r.PaymentStatus, "amount": r.PaymentAmount, "paidAt": r.PaidAt.UTC().Format(time.RFC3339)},
		"createdAt": r.OrderCreatedAt.UTC().Format(time.RFC3339), "updatedAt": r.OrderUpdatedAt.UTC().Format(time.RFC3339),
	}
}

func itemJSON(r orderRow) map[string]any {
	return map[string]any{
		"id": r.ItemID, "quantity": r.Quantity, "unitPrice": r.ItemUnitPrice, "totalPrice": r.ItemTotalPrice,
		"product": map[string]any{"id": r.ProductID, "categoryId": r.CategoryID, "categoryName": r.CategoryName, "sku": r.SKU, "name": r.ProductName, "unitPrice": r.ProductUnitPrice, "stockQuantity": r.StockQuantity, "active": r.Active},
	}
}

func nullableString(value sql.NullString) any {
	if value.Valid {
		return value.String
	}
	return nil
}

func decodeJSON(r *http.Request, target any) error {
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: []map[string]string{{"field": "$", "message": "Invalid JSON"}}}
	}
	return nil
}

func validateCreateCustomer(p createCustomerRequest) error {
	details := []map[string]string{}
	required(&details, "fullName", p.FullName)
	required(&details, "email", p.Email)
	required(&details, "documentNumber", p.DocumentNumber)
	validateAddress(&details, p.Address)
	if p.Email != "" && !strings.Contains(p.Email, "@") {
		details = append(details, map[string]string{"field": "email", "message": "Must be a valid email-like value"})
	}
	return detailsError(details)
}

func validateUpdateCustomer(p updateCustomerRequest) error {
	details := []map[string]string{}
	required(&details, "fullName", p.FullName)
	required(&details, "status", p.Status)
	if p.Status != "" && p.Status != "active" && p.Status != "inactive" {
		details = append(details, map[string]string{"field": "status", "message": "Must be active or inactive"})
	}
	validateAddress(&details, p.Address)
	return detailsError(details)
}

func validateCreateOrder(p createOrderRequest) error {
	details := []map[string]string{}
	if p.CustomerID <= 0 {
		details = append(details, map[string]string{"field": "customerId", "message": "Must be a positive integer"})
	}
	if p.AddressID <= 0 {
		details = append(details, map[string]string{"field": "addressId", "message": "Must be a positive integer"})
	}
	if len(p.Items) == 0 {
		details = append(details, map[string]string{"field": "items", "message": "Must contain at least one item"})
	}
	for i, item := range p.Items {
		if item.ProductID <= 0 {
			details = append(details, map[string]string{"field": fmt.Sprintf("items[%d].productId", i), "message": "Must be a positive integer"})
		}
		if item.Quantity <= 0 {
			details = append(details, map[string]string{"field": fmt.Sprintf("items[%d].quantity", i), "message": "Must be a positive integer"})
		}
	}
	method := p.Payment.Method
	if method != "credit_card" && method != "debit_card" && method != "pix" && method != "boleto" {
		details = append(details, map[string]string{"field": "payment.method", "message": "Invalid payment method"})
	}
	return detailsError(details)
}

func validateAddress(details *[]map[string]string, a addressInput) {
	required(details, "address.label", a.Label)
	required(details, "address.street", a.Street)
	required(details, "address.number", a.Number)
	required(details, "address.district", a.District)
	required(details, "address.city", a.City)
	required(details, "address.state", a.State)
	required(details, "address.postalCode", a.PostalCode)
}

func required(details *[]map[string]string, field, value string) {
	if strings.TrimSpace(value) == "" {
		*details = append(*details, map[string]string{"field": field, "message": "Required non-empty string"})
	}
}

func detailsError(details []map[string]string) error {
	if len(details) > 0 {
		return apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: details}
	}
	return nil
}

func pagination(r *http.Request) (int, int, error) {
	page, err := positiveInt(defaultString(r.URL.Query().Get("page"), "1"), "page")
	if err != nil {
		return 0, 0, err
	}
	pageSize, err := positiveInt(defaultString(r.URL.Query().Get("pageSize"), "50"), "pageSize")
	if err != nil {
		return 0, 0, err
	}
	if pageSize > 100 {
		return 0, 0, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request parameter", Details: []map[string]string{{"field": "pageSize", "message": "Must be between 1 and 100"}}}
	}
	return page, pageSize, nil
}

func pathID(path, prefix string) (int, error) {
	return positiveInt(strings.TrimPrefix(path, prefix), "id")
}

func positiveInt(value, field string) (int, error) {
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return 0, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request parameter", Details: []map[string]string{{"field": field, "message": "Must be a positive integer"}}}
	}
	return parsed, nil
}

func defaultString(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func notFoundOrDB(err error, message string) error {
	if errors.Is(err, sql.ErrNoRows) {
		return apiError{Status: 404, Code: "NOT_FOUND", Message: message}
	}
	return dbError(err)
}

func dbError(err error) error {
	return apiError{Status: 500, Code: "DATABASE_ERROR", Message: "Database error", Details: []map[string]string{{"message": err.Error()}}}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, err error) {
	var api apiError
	if errors.As(err, &api) {
		writeJSON(w, api.Status, map[string]any{"error": map[string]any{"code": api.Code, "message": api.Message, "details": api.Details}})
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]any{"error": map[string]any{"code": "INTERNAL_ERROR", "message": "Internal server error", "details": []map[string]string{{"message": err.Error()}}}})
}

const getCustomerSQL = `
SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
WHERE c.id = $1`

const listCustomersSQL = `
SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
ORDER BY c.created_at, c.id
LIMIT $1 OFFSET $2`

const listProductsSQL = `
SELECT id, category_id, sku, name, unit_price::text, stock_quantity, active
FROM products
WHERE category_id = $1 AND active = true
ORDER BY id`

const insertCustomerSQL = `
INSERT INTO customers (full_name, email, document_number, phone, status)
VALUES ($1, $2, $3, $4, 'active')
RETURNING id`

const insertAddressSQL = `
INSERT INTO addresses (customer_id, label, street, number, complement, district, city, state, postal_code, is_default)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`

const insertAuditSQL = `
INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ($1, $2, $3, $4::jsonb)`

const updateCustomerSQL = `
UPDATE customers SET full_name = $1, phone = $2, status = $3, updated_at = now()
WHERE id = $4`

const updateAddressSQL = `
UPDATE addresses
SET label = $1, street = $2, number = $3, complement = $4, district = $5, city = $6, state = $7, postal_code = $8, is_default = $9
WHERE customer_id = $10 AND is_default = true`

const getOrderSQL = `
SELECT o.id, o.status, o.total_amount::text, o.created_at, o.updated_at,
       c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default,
       oi.id, oi.quantity, oi.unit_price::text, oi.total_price::text,
       p.id, p.sku, p.name, p.unit_price::text, p.stock_quantity, p.active,
       cat.id, cat.name,
       pay.id, pay.method, pay.status, pay.amount::text, pay.paid_at
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN addresses a ON a.id = o.address_id
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
JOIN categories cat ON cat.id = p.category_id
JOIN payments pay ON pay.order_id = o.id
WHERE o.id = $1
ORDER BY oi.id`
