package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"math/big"
	"net/http"
	"os"
	"runtime"
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
	IsDefault  *bool   `json:"isDefault"`
}

type createCustomerRequest struct {
	FullName       string        `json:"fullName"`
	Email          string        `json:"email"`
	DocumentNumber string        `json:"documentNumber"`
	Phone          *string       `json:"phone"`
	Address        *addressInput `json:"address"`
}

type updateCustomerRequest struct {
	FullName string        `json:"fullName"`
	Phone    *string       `json:"phone"`
	Status   string        `json:"status"`
	Address  *addressInput `json:"address"`
}

type integerInput struct {
	Value int
	Valid bool
}

func (value *integerInput) UnmarshalJSON(data []byte) error {
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.UseNumber()
	var raw any
	if err := decoder.Decode(&raw); err != nil {
		return err
	}
	number, ok := raw.(json.Number)
	if !ok {
		return nil
	}
	parsed, err := strconv.ParseFloat(number.String(), 64)
	if err != nil || parsed < 1 || parsed > math.MaxInt32 || math.Trunc(parsed) != parsed {
		return nil
	}
	value.Value = int(parsed)
	value.Valid = true
	return nil
}

func (value integerInput) MarshalJSON() ([]byte, error) {
	return []byte(strconv.Itoa(value.Value)), nil
}

type orderItemInput struct {
	ProductID integerInput `json:"productId"`
	Quantity  integerInput `json:"quantity"`
}

type paymentInput struct {
	Method string `json:"method"`
}

type createOrderRequest struct {
	CustomerID integerInput     `json:"customerId"`
	AddressID  integerInput     `json:"addressId"`
	Items      []orderItemInput `json:"items"`
	Payment    *paymentInput    `json:"payment"`
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
	if len(os.Args) == 2 && os.Args[1] == "--runtime-version" {
		fmt.Println(runtime.Version())
		return
	}
	cfg := loadSettings()
	db, err := sql.Open("postgres", cfg.databaseURL)
	if err != nil {
		log.Fatal(err)
	}
	db.SetMaxOpenConns(cfg.poolMax)
	// Keep burst connections reusable. Mapping poolMin to MaxIdleConns caused
	// thousands of reconnects because database/sql has no minimum-idle setting.
	db.SetMaxIdleConns(cfg.poolMax)
	db.SetConnMaxIdleTime(time.Duration(cfg.idleTimeout) * time.Second)
	db.SetConnMaxLifetime(time.Duration(cfg.maxLifetime) * time.Second)

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.acquireTimeout)*time.Second)
	defer cancel()
	if err := warmPool(ctx, db, cfg.poolMin); err != nil {
		log.Fatal(err)
	}

	application := &app{db: db, settings: cfg}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", application.health)
	mux.HandleFunc("/customers", application.withDatabaseTimeout(application.customers))
	mux.HandleFunc("/customers/", application.withDatabaseTimeout(application.customerByID))
	mux.HandleFunc("/products", application.withDatabaseTimeout(application.products))
	mux.HandleFunc("/orders", application.withDatabaseTimeout(application.orders))
	mux.HandleFunc("/orders/", application.withDatabaseTimeout(application.orderByID))
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, pattern := mux.Handler(r)
		if pattern == "" {
			writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
			return
		}
		mux.ServeHTTP(w, r)
	})

	server := &http.Server{
		Addr:              "0.0.0.0:" + cfg.port,
		Handler:           recoverInternalErrors(handler),
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("Go API listening on %s", cfg.port)
	log.Fatal(server.ListenAndServe())
}

func recoverInternalErrors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recover() != nil {
				writeError(w, apiError{Status: 500, Code: "INTERNAL_ERROR", Message: "Internal server error"})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func warmPool(ctx context.Context, db *sql.DB, minimum int) error {
	connections := make([]*sql.Conn, 0, minimum)
	for i := 0; i < minimum; i++ {
		conn, err := db.Conn(ctx)
		if err != nil {
			for _, opened := range connections {
				opened.Close()
			}
			return err
		}
		connections = append(connections, conn)
	}
	for _, conn := range connections {
		if err := conn.Close(); err != nil {
			return err
		}
	}
	return nil
}

func (a *app) withDatabaseTimeout(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), time.Duration(a.settings.acquireTimeout)*time.Second)
		defer cancel()
		next(w, r.WithContext(ctx))
	}
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
		maxLifetime:    intEnv("DB_POOL_MAX_LIFETIME_SECONDS", 1800),
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
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
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
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
	}
}

func (a *app) customerByID(w http.ResponseWriter, r *http.Request) {
	if !isEntityPath(r.URL.Path, "/customers/") {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
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
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
	}
}

func (a *app) products(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
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
			"unitPrice": money(price), "stockQuantity": stock, "active": active,
		})
	}
	if err := rows.Err(); err != nil {
		writeError(w, dbError(err))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"categoryId": categoryID, "items": items})
}

func (a *app) orders(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
		return
	}
	a.createOrder(w, r)
}

func (a *app) orderByID(w http.ResponseWriter, r *http.Request) {
	if !isEntityPath(r.URL.Path, "/orders/") {
		writeError(w, apiError{Status: 404, Code: "NOT_FOUND", Message: "Route not found"})
		return
	}
	id, err := pathID(r.URL.Path, "/orders/")
	if err != nil {
		writeError(w, err)
		return
	}
	if r.Method != http.MethodGet {
		writeError(w, apiError{Status: 405, Code: "METHOD_NOT_ALLOWED", Message: "Method not allowed"})
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
	if err := rows.Err(); err != nil {
		writeError(w, dbError(err))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"page": page, "pageSize": pageSize, "total": total, "items": items})
}

func (a *app) createCustomer(w http.ResponseWriter, r *http.Request) {
	raw, err := decodeJSON(r)
	if err != nil {
		writeError(w, err)
		return
	}
	payload, err := validateCreateCustomer(raw)
	if err != nil {
		writeError(w, err)
		return
	}
	address := payload.Address
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
	if _, err := tx.ExecContext(r.Context(), insertAddressSQL, customerID, address.Label, address.Street, address.Number, address.Complement, address.District, address.City, address.State, address.PostalCode, *address.IsDefault); err != nil {
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
	raw, err := decodeJSON(r)
	if err != nil {
		writeError(w, err)
		return
	}
	payload, err := validateUpdateCustomer(raw)
	if err != nil {
		writeError(w, err)
		return
	}
	address := payload.Address
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
	addressResult, err := tx.ExecContext(r.Context(), updateAddressSQL, address.Label, address.Street, address.Number, address.Complement, address.District, address.City, address.State, address.PostalCode, *address.IsDefault, id)
	if err != nil {
		writeError(w, dbError(err))
		return
	}
	addressCount, _ := addressResult.RowsAffected()
	if addressCount == 0 {
		if _, err := tx.ExecContext(r.Context(), insertAddressSQL, id, address.Label, address.Street, address.Number, address.Complement, address.District, address.City, address.State, address.PostalCode, *address.IsDefault); err != nil {
			writeError(w, dbError(err))
			return
		}
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
	raw, err := decodeJSON(r)
	if err != nil {
		writeError(w, err)
		return
	}
	payload, err := validateCreateOrder(raw)
	if err != nil {
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
	if err := tx.QueryRowContext(r.Context(), "SELECT id FROM customers WHERE id = $1 AND status = 'active'", payload.CustomerID.Value).Scan(&exists); err != nil {
		writeError(w, notFoundOrDB(err, "Customer not found"))
		return
	}
	if err := tx.QueryRowContext(r.Context(), "SELECT id FROM addresses WHERE id = $1 AND customer_id = $2", payload.AddressID.Value, payload.CustomerID.Value).Scan(&exists); err != nil {
		writeError(w, notFoundOrDB(err, "Address not found"))
		return
	}
	var orderID int
	if err := tx.QueryRowContext(r.Context(), "INSERT INTO orders (customer_id, address_id, status, total_amount) VALUES ($1, $2, 'created', 0) RETURNING id", payload.CustomerID.Value, payload.AddressID.Value).Scan(&orderID); err != nil {
		writeError(w, dbError(err))
		return
	}
	for _, item := range payload.Items {
		var productID, stock int
		var price string
		if err := tx.QueryRowContext(r.Context(), "SELECT id, unit_price, stock_quantity FROM products WHERE id = $1 AND active = true FOR UPDATE", item.ProductID.Value).Scan(&productID, &price, &stock); err != nil {
			writeError(w, notFoundOrDB(err, "Product not found"))
			return
		}
		if stock < item.Quantity.Value {
			writeError(w, apiError{Status: 409, Code: "CONFLICT", Message: "Insufficient stock"})
			return
		}
		res, err := tx.ExecContext(r.Context(), "UPDATE products SET stock_quantity = stock_quantity - $1 WHERE id = $2 AND stock_quantity >= $3", item.Quantity.Value, item.ProductID.Value, item.Quantity.Value)
		if err != nil {
			writeError(w, dbError(err))
			return
		}
		count, _ := res.RowsAffected()
		if count == 0 {
			writeError(w, apiError{Status: 409, Code: "CONFLICT", Message: "Insufficient stock"})
			return
		}
		if _, err := tx.ExecContext(r.Context(), "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)", orderID, item.ProductID.Value, item.Quantity.Value, price); err != nil {
			writeError(w, dbError(err))
			return
		}
	}
	var total string
	if err := tx.QueryRowContext(r.Context(), "UPDATE orders SET total_amount = (SELECT sum(total_price)::numeric(12, 2) FROM order_items WHERE order_id = $1), status = 'paid', updated_at = now() WHERE id = $2 RETURNING total_amount", orderID, orderID).Scan(&total); err != nil {
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
		if err := rows.Err(); err != nil {
			return nil, dbError(err)
		}
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
	if err := rows.Err(); err != nil {
		return nil, dbError(err)
	}
	if first == nil {
		return nil, apiError{Status: 404, Code: "NOT_FOUND", Message: "Order not found"}
	}
	first["items"] = items
	return first, nil
}

type orderRow struct {
	OrderID, CustomerID, AddressID, ItemID, Quantity, ProductID, StockQuantity, CategoryID, PaymentID int64
	OrderStatus, TotalAmount, FullName, Email, DocumentNumber, CustomerStatus                         string
	Label, Street, Number, Complement, District, City, State, PostalCode                              sql.NullString
	ItemUnitPrice, ItemTotalPrice, SKU, ProductName, ProductUnitPrice, CategoryName                   string
	PaymentMethod, PaymentStatus, PaymentAmount                                                       string
	Active, IsDefault                                                                                 bool
	Phone                                                                                             sql.NullString
	OrderCreatedAt, OrderUpdatedAt, CustomerCreatedAt, CustomerUpdatedAt                              time.Time
	PaidAt                                                                                             sql.NullTime
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
		"id": r.OrderID, "status": r.OrderStatus, "totalAmount": money(r.TotalAmount),
		"customer":  map[string]any{"id": r.CustomerID, "fullName": r.FullName, "email": r.Email, "documentNumber": r.DocumentNumber, "phone": nullableString(r.Phone), "status": r.CustomerStatus, "address": addr, "createdAt": r.CustomerCreatedAt.UTC().Format(time.RFC3339), "updatedAt": r.CustomerUpdatedAt.UTC().Format(time.RFC3339)},
		"address":   addr,
		"payment":   map[string]any{"id": r.PaymentID, "method": r.PaymentMethod, "status": r.PaymentStatus, "amount": money(r.PaymentAmount), "paidAt": nullableInstant(r.PaidAt)},
		"createdAt": r.OrderCreatedAt.UTC().Format(time.RFC3339), "updatedAt": r.OrderUpdatedAt.UTC().Format(time.RFC3339),
	}
}

func itemJSON(r orderRow) map[string]any {
	return map[string]any{
		"id": r.ItemID, "quantity": r.Quantity, "unitPrice": money(r.ItemUnitPrice), "totalPrice": money(r.ItemTotalPrice),
		"product": map[string]any{"id": r.ProductID, "categoryId": r.CategoryID, "categoryName": r.CategoryName, "sku": r.SKU, "name": r.ProductName, "unitPrice": money(r.ProductUnitPrice), "stockQuantity": r.StockQuantity, "active": r.Active},
	}
}

func nullableString(value sql.NullString) any {
	if value.Valid {
		return value.String
	}
	return nil
}

func nullableInstant(value sql.NullTime) any {
	if value.Valid {
		return value.Time.UTC().Format(time.RFC3339)
	}
	return nil
}

func decodeJSON(r *http.Request) (map[string]any, error) {
	raw, err := io.ReadAll(r.Body)
	if err != nil || !json.Valid(raw) {
		return nil, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: []map[string]string{{"field": "$", "message": "Invalid JSON"}}}
	}
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var decoded any
	if err := decoder.Decode(&decoded); err != nil {
		return nil, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: []map[string]string{{"field": "$", "message": "Invalid JSON"}}}
	}
	object, ok := decoded.(map[string]any)
	if !ok {
		return nil, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: []map[string]string{{"field": "$", "message": "Must be a JSON object"}}}
	}
	return object, nil
}

func validateCreateCustomer(raw map[string]any) (createCustomerRequest, error) {
	details := []map[string]string{}
	p := createCustomerRequest{
		FullName:       requiredString(raw, "fullName", "fullName", &details),
		Email:          requiredString(raw, "email", "email", &details),
		DocumentNumber: requiredString(raw, "documentNumber", "documentNumber", &details),
		Phone:          optionalString(raw, "phone", "phone", &details),
		Address:        normalizedAddress(raw["address"], &details),
	}
	if p.Email != "" && !strings.Contains(p.Email, "@") {
		details = append(details, map[string]string{"field": "email", "message": "Must be a valid email-like value"})
	}
	return p, detailsError(details)
}

func validateUpdateCustomer(raw map[string]any) (updateCustomerRequest, error) {
	details := []map[string]string{}
	p := updateCustomerRequest{
		FullName: requiredString(raw, "fullName", "fullName", &details),
		Status:   requiredString(raw, "status", "status", &details),
	}
	if p.Status != "" && p.Status != "active" && p.Status != "inactive" {
		details = append(details, map[string]string{"field": "status", "message": "Must be active or inactive"})
	}
	p.Phone = optionalString(raw, "phone", "phone", &details)
	p.Address = normalizedAddress(raw["address"], &details)
	return p, detailsError(details)
}

func validateCreateOrder(raw map[string]any) (createOrderRequest, error) {
	details := []map[string]string{}
	p := createOrderRequest{
		CustomerID: normalizedInteger(raw["customerId"], "customerId", &details),
		AddressID:  normalizedInteger(raw["addressId"], "addressId", &details),
		Items:      []orderItemInput{},
	}
	rawItems, ok := raw["items"].([]any)
	if !ok || len(rawItems) == 0 {
		details = append(details, map[string]string{"field": "items", "message": "Must contain at least one item"})
	} else {
		for i, rawItem := range rawItems {
			item, ok := rawItem.(map[string]any)
			if !ok {
				details = append(details, map[string]string{"field": fmt.Sprintf("items[%d]", i), "message": "Must be an object"})
				continue
			}
			p.Items = append(p.Items, orderItemInput{
				ProductID: normalizedInteger(item["productId"], fmt.Sprintf("items[%d].productId", i), &details),
				Quantity:  normalizedInteger(item["quantity"], fmt.Sprintf("items[%d].quantity", i), &details),
			})
		}
	}
	payment, ok := raw["payment"].(map[string]any)
	if !ok {
		details = append(details, map[string]string{"field": "payment", "message": "Required object"})
	} else {
		method := requiredString(payment, "method", "payment.method", &details)
		p.Payment = &paymentInput{Method: method}
		if method != "" && method != "credit_card" && method != "debit_card" && method != "pix" && method != "boleto" {
			details = append(details, map[string]string{"field": "payment.method", "message": "Invalid payment method"})
		}
	}
	return p, detailsError(details)
}

func normalizedAddress(value any, details *[]map[string]string) *addressInput {
	raw, ok := value.(map[string]any)
	if !ok {
		*details = append(*details, map[string]string{"field": "address", "message": "Required object"})
		return nil
	}
	a := &addressInput{
		Label:      requiredString(raw, "label", "address.label", details),
		Street:     requiredString(raw, "street", "address.street", details),
		Number:     requiredString(raw, "number", "address.number", details),
		Complement: optionalString(raw, "complement", "address.complement", details),
		District:   requiredString(raw, "district", "address.district", details),
		City:       requiredString(raw, "city", "address.city", details),
		State:      requiredString(raw, "state", "address.state", details),
		PostalCode: requiredString(raw, "postalCode", "address.postalCode", details),
	}
	if value, ok := raw["isDefault"].(bool); ok {
		a.IsDefault = &value
	} else {
		*details = append(*details, map[string]string{"field": "address.isDefault", "message": "Required boolean"})
	}
	if a.State != "" && !asciiState(a.State) {
		*details = append(*details, map[string]string{"field": "address.state", "message": "Must contain exactly 2 ASCII letters"})
	} else if a.State != "" {
		a.State = strings.ToUpper(a.State)
	}
	return a
}

func asciiState(value string) bool {
	if len(value) != 2 {
		return false
	}
	for _, character := range []byte(value) {
		if (character < 'A' || character > 'Z') && (character < 'a' || character > 'z') {
			return false
		}
	}
	return true
}

func requiredString(raw map[string]any, key, field string, details *[]map[string]string) string {
	value, ok := raw[key].(string)
	if !ok || strings.TrimSpace(value) == "" {
		*details = append(*details, map[string]string{"field": field, "message": "Required non-empty string"})
		return ""
	}
	return strings.TrimSpace(value)
}

func optionalString(raw map[string]any, key, field string, details *[]map[string]string) *string {
	value, exists := raw[key]
	if !exists || value == nil {
		return nil
	}
	text, ok := value.(string)
	if !ok {
		*details = append(*details, map[string]string{"field": field, "message": "Must be a string or null"})
		return nil
	}
	trimmed := strings.TrimSpace(text)
	return &trimmed
}

func normalizedInteger(value any, field string, details *[]map[string]string) integerInput {
	number, ok := value.(json.Number)
	if !ok {
		*details = append(*details, map[string]string{"field": field, "message": "Must be a positive integer"})
		return integerInput{}
	}
	parsed, err := strconv.ParseFloat(number.String(), 64)
	if err != nil || parsed < 1 || parsed > math.MaxInt32 || math.Trunc(parsed) != parsed {
		*details = append(*details, map[string]string{"field": field, "message": "Must be a positive integer"})
		return integerInput{}
	}
	return integerInput{Value: int(parsed), Valid: true}
}

func detailsError(details []map[string]string) error {
	if len(details) > 0 {
		return apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request payload", Details: details}
	}
	return nil
}

func pagination(r *http.Request) (int, int, error) {
	query := r.URL.Query()
	pageText := "1"
	if _, exists := query["page"]; exists {
		pageText = query.Get("page")
	}
	page, err := positiveInt(pageText, "page")
	if err != nil {
		return 0, 0, err
	}
	pageSizeText := "50"
	if _, exists := query["pageSize"]; exists {
		pageSizeText = query.Get("pageSize")
	}
	pageSize, err := positiveInt(pageSizeText, "pageSize")
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

func isEntityPath(path, prefix string) bool {
	value := strings.TrimPrefix(path, prefix)
	return strings.HasPrefix(path, prefix) && value != "" && !strings.Contains(value, "/")
}

func positiveInt(value, field string) (int, error) {
	if value == "" || strings.IndexFunc(value, func(character rune) bool { return character < '0' || character > '9' }) != -1 {
		return 0, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request parameter", Details: []map[string]string{{"field": field, "message": "Must be a positive integer"}}}
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 || parsed > math.MaxInt32 {
		return 0, apiError{Status: 400, Code: "VALIDATION_ERROR", Message: "Invalid request parameter", Details: []map[string]string{{"field": field, "message": "Must be a positive integer"}}}
	}
	return parsed, nil
}

func money(raw string) string {
	value, ok := new(big.Rat).SetString(raw)
	if !ok {
		return raw
	}
	return value.FloatString(2)
}

func notFoundOrDB(err error, message string) error {
	if errors.Is(err, sql.ErrNoRows) {
		return apiError{Status: 404, Code: "NOT_FOUND", Message: message}
	}
	return dbError(err)
}

func dbError(err error) error {
	return apiError{Status: 500, Code: "DATABASE_ERROR", Message: "Database error"}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	encoded, err := json.Marshal(body)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":{"code":"INTERNAL_ERROR","message":"Internal server error","details":[]}}`))
		return
	}
	w.WriteHeader(status)
	_, _ = w.Write(encoded)
}

func writeError(w http.ResponseWriter, err error) {
	var api apiError
	if errors.As(err, &api) {
		details := api.Details
		if details == nil {
			details = []map[string]string{}
		}
		writeJSON(w, api.Status, map[string]any{"error": map[string]any{"code": api.Code, "message": api.Message, "details": details}})
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]any{"error": map[string]any{"code": "INTERNAL_ERROR", "message": "Internal server error", "details": []map[string]string{}}})
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
SELECT id, category_id, sku, name, unit_price, stock_quantity, active
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
SELECT o.id, o.status, o.total_amount, o.created_at, o.updated_at,
       c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default,
       oi.id, oi.quantity, oi.unit_price, oi.total_price,
       p.id, p.sku, p.name, p.unit_price, p.stock_quantity, p.active,
       cat.id, cat.name,
       pay.id, pay.method, pay.status, pay.amount, pay.paid_at
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN addresses a ON a.id = o.address_id
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
JOIN categories cat ON cat.id = p.category_id
JOIN payments pay ON pay.order_id = o.id
WHERE o.id = $1
ORDER BY oi.id`
