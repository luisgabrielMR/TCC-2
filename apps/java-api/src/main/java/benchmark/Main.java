package benchmark;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.sql.*;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.concurrent.Executors;

public class Main {
    private static final ObjectMapper JSON = new ObjectMapper()
        .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS);
    private static final DateTimeFormatter INSTANT = DateTimeFormatter.ISO_INSTANT;
    private final HikariDataSource dataSource;

    public Main(HikariDataSource dataSource) {
        this.dataSource = dataSource;
    }

    public static void main(String[] args) throws Exception {
        var app = new Main(createDataSource());
        var server = HttpServer.create(new InetSocketAddress("0.0.0.0", intEnv("PORT", 8000)), 0);
        server.createContext("/health", app::health);
        server.createContext("/customers", app::customers);
        server.createContext("/products", app::products);
        server.createContext("/orders", app::orders);
        server.createContext("/", app::routeNotFound);
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.start();
        System.out.println("Java API listening on 8000");
    }

    private static HikariDataSource createDataSource() {
        var config = new HikariConfig();
        config.setJdbcUrl(jdbcUrl());
        config.setUsername(env("POSTGRES_USER", "benchmark_user"));
        config.setPassword(env("POSTGRES_PASSWORD", "benchmark_password"));
        config.setMinimumIdle(intEnv("DB_POOL_MIN", 1));
        config.setMaximumPoolSize(intEnv("DB_POOL_MAX", 20));
        config.setConnectionTimeout(intEnv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10) * 1000L);
        config.setIdleTimeout(intEnv("DB_POOL_IDLE_TIMEOUT_SECONDS", 60) * 1000L);
        config.setMaxLifetime(intEnv("DB_POOL_MAX_LIFETIME_SECONDS", 1800) * 1000L);
        return new HikariDataSource(config);
    }

    private void health(HttpExchange exchange) throws IOException {
        if (!exchange.getRequestURI().getPath().equals("/health")) {
            writeError(exchange, new ApiError(404, "NOT_FOUND", "Route not found"));
            return;
        }
        if (!method(exchange, "GET")) return;
        write(exchange, 200, Map.of("status", "ok"));
    }

    private void routeNotFound(HttpExchange exchange) throws IOException {
        writeError(exchange, new ApiError(404, "NOT_FOUND", "Route not found"));
    }

    private void customers(HttpExchange exchange) throws IOException {
        try {
            var path = exchange.getRequestURI().getPath();
            if (path.equals("/customers") && exchange.getRequestMethod().equals("GET")) {
                listCustomers(exchange);
            } else if (path.equals("/customers") && exchange.getRequestMethod().equals("POST")) {
                createCustomer(exchange);
            } else if (isEntityPath(path, "/customers/")) {
                if (exchange.getRequestMethod().equals("GET")) {
                    getCustomer(exchange, pathId(path, "/customers/"));
                } else if (exchange.getRequestMethod().equals("PUT")) {
                    updateCustomer(exchange, pathId(path, "/customers/"));
                } else {
                    writeError(exchange, new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed"));
                }
            } else if (path.equals("/customers")) {
                writeError(exchange, new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed"));
            } else {
                writeError(exchange, new ApiError(404, "NOT_FOUND", "Route not found"));
            }
        } catch (ApiError error) {
            writeError(exchange, error);
        } catch (Exception error) {
            writeError(exchange, serverError(error));
        }
    }

    private void products(HttpExchange exchange) throws IOException {
        try {
            if (!exchange.getRequestURI().getPath().equals("/products")) {
                writeError(exchange, new ApiError(404, "NOT_FOUND", "Route not found"));
                return;
            }
            if (!method(exchange, "GET")) return;
            var categoryId = positiveInt(query(exchange).getOrDefault("categoryId", ""), "categoryId");
            try (var conn = dataSource.getConnection()) {
                try (var check = conn.prepareStatement("SELECT id FROM categories WHERE id = ?")) {
                    check.setInt(1, categoryId);
                    try (var rs = check.executeQuery()) {
                        if (!rs.next()) throw new ApiError(404, "NOT_FOUND", "Category not found");
                    }
                }
                var items = new ArrayList<Map<String, Object>>();
                try (var ps = conn.prepareStatement(LIST_PRODUCTS)) {
                    ps.setInt(1, categoryId);
                    try (var rs = ps.executeQuery()) {
                        while (rs.next()) {
                            items.add(mapOf(
                                "id", rs.getLong("id"),
                                "categoryId", rs.getLong("category_id"),
                                "sku", rs.getString("sku"),
                                "name", rs.getString("name"),
                                "unitPrice", money(rs.getBigDecimal("unit_price")),
                                "stockQuantity", rs.getInt("stock_quantity"),
                                "active", rs.getBoolean("active")
                            ));
                        }
                    }
                }
                write(exchange, 200, mapOf("categoryId", categoryId, "items", items));
            }
        } catch (ApiError error) {
            writeError(exchange, error);
        } catch (Exception error) {
            writeError(exchange, serverError(error));
        }
    }

    private void orders(HttpExchange exchange) throws IOException {
        try {
            var path = exchange.getRequestURI().getPath();
            if (path.equals("/orders") && exchange.getRequestMethod().equals("POST")) {
                createOrder(exchange);
            } else if (isEntityPath(path, "/orders/")) {
                if (exchange.getRequestMethod().equals("GET")) {
                    getOrder(exchange, pathId(path, "/orders/"));
                } else {
                    writeError(exchange, new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed"));
                }
            } else if (path.equals("/orders")) {
                writeError(exchange, new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed"));
            } else {
                writeError(exchange, new ApiError(404, "NOT_FOUND", "Route not found"));
            }
        } catch (ApiError error) {
            writeError(exchange, error);
        } catch (Exception error) {
            writeError(exchange, serverError(error));
        }
    }

    private void getCustomer(HttpExchange exchange, int id) throws Exception {
        try (var conn = dataSource.getConnection()) {
            var customer = fetchCustomer(conn, id);
            if (customer == null) throw new ApiError(404, "NOT_FOUND", "Customer not found");
            write(exchange, 200, customer);
        }
    }

    private void listCustomers(HttpExchange exchange) throws Exception {
        var params = query(exchange);
        var page = positiveInt(params.getOrDefault("page", "1"), "page");
        var pageSize = positiveInt(params.getOrDefault("pageSize", "50"), "pageSize");
        if (pageSize > 100) throw new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", detail("pageSize", "Must be between 1 and 100"));
        var offset = (page - 1) * pageSize;
        try (var conn = dataSource.getConnection()) {
            int total;
            try (var ps = conn.prepareStatement("SELECT count(*)::int FROM customers"); var rs = ps.executeQuery()) {
                rs.next();
                total = rs.getInt(1);
            }
            var items = new ArrayList<Map<String, Object>>();
            try (var ps = conn.prepareStatement(LIST_CUSTOMERS)) {
                ps.setInt(1, pageSize);
                ps.setInt(2, offset);
                try (var rs = ps.executeQuery()) {
                    while (rs.next()) items.add(customerFromRow(rs));
                }
            }
            write(exchange, 200, mapOf("page", page, "pageSize", pageSize, "total", total, "items", items));
        }
    }

    private void createCustomer(HttpExchange exchange) throws Exception {
        var payload = readBody(exchange);
        validateCreateCustomer(payload);
        try (var conn = dataSource.getConnection()) {
            conn.setAutoCommit(false);
            try {
                int customerId;
                try (var ps = conn.prepareStatement(INSERT_CUSTOMER)) {
                    ps.setString(1, string(payload, "fullName"));
                    ps.setString(2, string(payload, "email"));
                    ps.setString(3, string(payload, "documentNumber"));
                    ps.setObject(4, payload.get("phone"));
                    try (var rs = ps.executeQuery()) {
                        rs.next();
                        customerId = rs.getInt(1);
                    }
                }
                insertAddress(conn, customerId, object(payload, "address"));
                insertAudit(conn, "customer", customerId, "create_customer", payload);
                var customer = fetchCustomer(conn, customerId);
                conn.commit();
                write(exchange, 201, customer);
            } catch (SQLException error) {
                conn.rollback();
                if ("23505".equals(error.getSQLState())) throw new ApiError(409, "CONFLICT", "Customer email or document already exists");
                throw error;
            } catch (Exception error) {
                conn.rollback();
                throw error;
            }
        }
    }

    private void updateCustomer(HttpExchange exchange, int id) throws Exception {
        var payload = readBody(exchange);
        validateUpdateCustomer(payload);
        try (var conn = dataSource.getConnection()) {
            conn.setAutoCommit(false);
            try {
                try (var ps = conn.prepareStatement(UPDATE_CUSTOMER)) {
                    ps.setString(1, string(payload, "fullName"));
                    ps.setObject(2, payload.get("phone"));
                    ps.setString(3, string(payload, "status"));
                    ps.setInt(4, id);
                    if (ps.executeUpdate() == 0) throw new ApiError(404, "NOT_FOUND", "Customer not found");
                }
                var address = object(payload, "address");
                if (updateAddress(conn, id, address) == 0) insertAddress(conn, id, address);
                insertAudit(conn, "customer", id, "update_customer", payload);
                var customer = fetchCustomer(conn, id);
                conn.commit();
                write(exchange, 200, customer);
            } catch (Exception error) {
                conn.rollback();
                throw error;
            }
        }
    }

    private void createOrder(HttpExchange exchange) throws Exception {
        var payload = readBody(exchange);
        validateCreateOrder(payload);
        try (var conn = dataSource.getConnection()) {
            conn.setAutoCommit(false);
            try {
                var customerId = number(payload, "customerId");
                var addressId = number(payload, "addressId");
                if (!exists(conn, "SELECT id FROM customers WHERE id = ? AND status = 'active'", customerId)) throw new ApiError(404, "NOT_FOUND", "Customer not found");
                if (!exists(conn, "SELECT id FROM addresses WHERE id = ? AND customer_id = ?", addressId, customerId)) throw new ApiError(404, "NOT_FOUND", "Address not found");
                int orderId;
                try (var ps = conn.prepareStatement("INSERT INTO orders (customer_id, address_id, status, total_amount) VALUES (?, ?, 'created', 0) RETURNING id")) {
                    ps.setInt(1, customerId);
                    ps.setInt(2, addressId);
                    try (var rs = ps.executeQuery()) {
                        rs.next();
                        orderId = rs.getInt(1);
                    }
                }
                for (var item : list(payload, "items")) {
                    var productId = number(item, "productId");
                    var quantity = number(item, "quantity");
                    BigDecimal unitPrice;
                    int stock;
                    try (var ps = conn.prepareStatement("SELECT unit_price, stock_quantity FROM products WHERE id = ? AND active = true FOR UPDATE")) {
                        ps.setInt(1, productId);
                        try (var rs = ps.executeQuery()) {
                            if (!rs.next()) throw new ApiError(404, "NOT_FOUND", "Product not found");
                            unitPrice = rs.getBigDecimal(1);
                            stock = rs.getInt(2);
                        }
                    }
                    if (stock < quantity) throw new ApiError(409, "CONFLICT", "Insufficient stock");
                    try (var ps = conn.prepareStatement("UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ? AND stock_quantity >= ?")) {
                        ps.setInt(1, quantity);
                        ps.setInt(2, productId);
                        ps.setInt(3, quantity);
                        if (ps.executeUpdate() == 0) throw new ApiError(409, "CONFLICT", "Insufficient stock");
                    }
                    try (var ps = conn.prepareStatement("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)")) {
                        ps.setInt(1, orderId);
                        ps.setInt(2, productId);
                        ps.setInt(3, quantity);
                        ps.setBigDecimal(4, unitPrice);
                        ps.executeUpdate();
                    }
                }
                BigDecimal total;
                try (var ps = conn.prepareStatement("UPDATE orders SET total_amount = (SELECT sum(total_price)::numeric(12, 2) FROM order_items WHERE order_id = ?), status = 'paid', updated_at = now() WHERE id = ? RETURNING total_amount")) {
                    ps.setInt(1, orderId);
                    ps.setInt(2, orderId);
                    try (var rs = ps.executeQuery()) {
                        rs.next();
                        total = rs.getBigDecimal(1);
                    }
                }
                var payment = object(payload, "payment");
                try (var ps = conn.prepareStatement("INSERT INTO payments (order_id, method, status, amount, paid_at) VALUES (?, ?, 'paid', ?, now())")) {
                    ps.setInt(1, orderId);
                    ps.setString(2, string(payment, "method"));
                    ps.setBigDecimal(3, total);
                    ps.executeUpdate();
                }
                insertAudit(conn, "order", orderId, "create_order", payload);
                var order = fetchOrder(conn, orderId);
                conn.commit();
                write(exchange, 201, order);
            } catch (Exception error) {
                conn.rollback();
                throw error;
            }
        }
    }

    private void getOrder(HttpExchange exchange, int id) throws Exception {
        try (var conn = dataSource.getConnection()) {
            var order = fetchOrder(conn, id);
            if (order == null) throw new ApiError(404, "NOT_FOUND", "Order not found");
            write(exchange, 200, order);
        }
    }

    private Map<String, Object> fetchCustomer(Connection conn, int id) throws Exception {
        try (var ps = conn.prepareStatement(GET_CUSTOMER)) {
            ps.setInt(1, id);
            try (var rs = ps.executeQuery()) {
                return rs.next() ? customerFromRow(rs) : null;
            }
        }
    }

    private Map<String, Object> fetchOrder(Connection conn, int id) throws Exception {
        try (var ps = conn.prepareStatement(GET_ORDER)) {
            ps.setInt(1, id);
            try (var rs = ps.executeQuery()) {
                Map<String, Object> order = null;
                var items = new ArrayList<Map<String, Object>>();
                while (rs.next()) {
                    var address = addressFromOrderRow(rs);
                    if (order == null) {
                        order = mapOf(
                            "id", rs.getLong("order_id"),
                            "status", rs.getString("order_status"),
                            "totalAmount", money(rs.getBigDecimal("total_amount")),
                            "customer", mapOf("id", rs.getLong("customer_id"), "fullName", rs.getString("full_name"), "email", rs.getString("email"), "documentNumber", rs.getString("document_number"), "phone", rs.getString("phone"), "status", rs.getString("customer_status"), "address", address, "createdAt", instant(rs.getTimestamp("customer_created_at")), "updatedAt", instant(rs.getTimestamp("customer_updated_at"))),
                            "address", address,
                            "items", items,
                            "payment", mapOf("id", rs.getLong("payment_id"), "method", rs.getString("payment_method"), "status", rs.getString("payment_status"), "amount", money(rs.getBigDecimal("payment_amount")), "paidAt", instant(rs.getTimestamp("paid_at"))),
                            "createdAt", instant(rs.getTimestamp("order_created_at")),
                            "updatedAt", instant(rs.getTimestamp("order_updated_at"))
                        );
                    }
                    items.add(mapOf(
                        "id", rs.getLong("item_id"),
                        "quantity", rs.getInt("quantity"),
                        "unitPrice", money(rs.getBigDecimal("item_unit_price")),
                        "totalPrice", money(rs.getBigDecimal("item_total_price")),
                        "product", mapOf("id", rs.getLong("product_id"), "categoryId", rs.getLong("category_id"), "categoryName", rs.getString("category_name"), "sku", rs.getString("sku"), "name", rs.getString("product_name"), "unitPrice", money(rs.getBigDecimal("product_unit_price")), "stockQuantity", rs.getInt("stock_quantity"), "active", rs.getBoolean("active"))
                    ));
                }
                return order;
            }
        }
    }

    private static Map<String, Object> customerFromRow(ResultSet rs) throws SQLException {
        return mapOf(
            "id", rs.getLong("id"),
            "fullName", rs.getString("full_name"),
            "email", rs.getString("email"),
            "documentNumber", rs.getString("document_number"),
            "phone", rs.getString("phone"),
            "status", rs.getString("status"),
            "address", addressFromCustomerRow(rs),
            "createdAt", instant(rs.getTimestamp("created_at")),
            "updatedAt", instant(rs.getTimestamp("updated_at"))
        );
    }

    private static Map<String, Object> addressFromCustomerRow(ResultSet rs) throws SQLException {
        var id = rs.getObject("address_id");
        if (id == null) return null;
        return mapOf("id", rs.getLong("address_id"), "label", rs.getString("label"), "street", rs.getString("street"), "number", rs.getString("number"), "complement", rs.getString("complement"), "district", rs.getString("district"), "city", rs.getString("city"), "state", rs.getString("state"), "postalCode", rs.getString("postal_code"), "isDefault", rs.getBoolean("is_default"));
    }

    private static Map<String, Object> addressFromOrderRow(ResultSet rs) throws SQLException {
        return mapOf("id", rs.getLong("address_id"), "label", rs.getString("label"), "street", rs.getString("street"), "number", rs.getString("number"), "complement", rs.getString("complement"), "district", rs.getString("district"), "city", rs.getString("city"), "state", rs.getString("state"), "postalCode", rs.getString("postal_code"), "isDefault", rs.getBoolean("is_default"));
    }

    private static void insertAddress(Connection conn, int customerId, Map<String, Object> address) throws SQLException {
        try (var ps = conn.prepareStatement(INSERT_ADDRESS)) {
            ps.setInt(1, customerId);
            ps.setString(2, string(address, "label"));
            ps.setString(3, string(address, "street"));
            ps.setString(4, string(address, "number"));
            ps.setObject(5, address.get("complement"));
            ps.setString(6, string(address, "district"));
            ps.setString(7, string(address, "city"));
            ps.setString(8, string(address, "state"));
            ps.setString(9, string(address, "postalCode"));
            ps.setBoolean(10, bool(address, "isDefault"));
            ps.executeUpdate();
        }
    }

    private static int updateAddress(Connection conn, int customerId, Map<String, Object> address) throws SQLException {
        try (var ps = conn.prepareStatement(UPDATE_ADDRESS)) {
            ps.setString(1, string(address, "label"));
            ps.setString(2, string(address, "street"));
            ps.setString(3, string(address, "number"));
            ps.setObject(4, address.get("complement"));
            ps.setString(5, string(address, "district"));
            ps.setString(6, string(address, "city"));
            ps.setString(7, string(address, "state"));
            ps.setString(8, string(address, "postalCode"));
            ps.setBoolean(9, bool(address, "isDefault"));
            ps.setInt(10, customerId);
            return ps.executeUpdate();
        }
    }

    private static void insertAudit(Connection conn, String entityType, int entityId, String action, Map<String, Object> payload) throws Exception {
        try (var ps = conn.prepareStatement("INSERT INTO audit_logs (entity_type, entity_id, action, payload) VALUES (?, ?, ?, ?::jsonb)")) {
            ps.setString(1, entityType);
            ps.setInt(2, entityId);
            ps.setString(3, action);
            ps.setString(4, JSON.writeValueAsString(payload));
            ps.executeUpdate();
        }
    }

    private static boolean exists(Connection conn, String sql, int... values) throws SQLException {
        try (var ps = conn.prepareStatement(sql)) {
            for (var i = 0; i < values.length; i++) ps.setInt(i + 1, values[i]);
            try (var rs = ps.executeQuery()) {
                return rs.next();
            }
        }
    }

    private static Map<String, Object> readBody(HttpExchange exchange) throws IOException {
        try {
            var value = JSON.readValue(exchange.getRequestBody(), Object.class);
            if (!(value instanceof Map<?, ?> raw)) {
                throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", detail("$", "Must be a JSON object"));
            }
            return castMap(raw);
        } catch (ApiError error) {
            throw error;
        } catch (Exception error) {
            throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", detail("$", "Invalid JSON"));
        }
    }

    private static void validateCreateCustomer(Map<String, Object> payload) {
        var details = new ArrayList<Map<String, String>>();
        payload.put("fullName", required(details, "fullName", payload.get("fullName")));
        payload.put("email", required(details, "email", payload.get("email")));
        payload.put("documentNumber", required(details, "documentNumber", payload.get("documentNumber")));
        payload.put("phone", optionalString(details, "phone", payload.get("phone")));
        payload.put("address", validateAddress(details, payload.get("address")));
        payload.keySet().retainAll(Set.of("fullName", "email", "documentNumber", "phone", "address"));
        var email = string(payload, "email");
        if (email != null && !email.isBlank() && !email.contains("@")) details.add(oneDetail("email", "Must be a valid email-like value"));
        if (!details.isEmpty()) throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
    }

    private static void validateUpdateCustomer(Map<String, Object> payload) {
        var details = new ArrayList<Map<String, String>>();
        payload.put("fullName", required(details, "fullName", payload.get("fullName")));
        payload.put("status", required(details, "status", payload.get("status")));
        var status = string(payload, "status");
        if (status != null && !status.isBlank() && !Set.of("active", "inactive").contains(status)) details.add(oneDetail("status", "Must be active or inactive"));
        payload.put("phone", optionalString(details, "phone", payload.get("phone")));
        payload.put("address", validateAddress(details, payload.get("address")));
        payload.keySet().retainAll(Set.of("fullName", "phone", "status", "address"));
        if (!details.isEmpty()) throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
    }

    private static void validateCreateOrder(Map<String, Object> payload) {
        var details = new ArrayList<Map<String, String>>();
        payload.put("customerId", normalizedNumber(payload.get("customerId"), "customerId", details));
        payload.put("addressId", normalizedNumber(payload.get("addressId"), "addressId", details));

        var normalizedItems = new ArrayList<Map<String, Object>>();
        var itemsValue = payload.get("items");
        if (!(itemsValue instanceof List<?> rawItems) || rawItems.isEmpty()) {
            details.add(oneDetail("items", "Must contain at least one item"));
        } else {
            for (var i = 0; i < rawItems.size(); i++) {
                var rawItem = rawItems.get(i);
                if (!(rawItem instanceof Map<?, ?> rawMap)) {
                    details.add(oneDetail("items[" + i + "]", "Must be an object"));
                    continue;
                }
                var item = castMap(rawMap);
                item.put("productId", normalizedNumber(item.get("productId"), "items[" + i + "].productId", details));
                item.put("quantity", normalizedNumber(item.get("quantity"), "items[" + i + "].quantity", details));
                item.keySet().retainAll(Set.of("productId", "quantity"));
                normalizedItems.add(item);
            }
        }
        payload.put("items", normalizedItems);

        var paymentValue = payload.get("payment");
        if (!(paymentValue instanceof Map<?, ?> rawPayment)) {
            details.add(oneDetail("payment", "Required object"));
            payload.put("payment", new HashMap<String, Object>());
        } else {
            var payment = castMap(rawPayment);
            var method = required(details, "payment.method", payment.get("method"));
            payment.put("method", method);
            payment.keySet().retainAll(Set.of("method"));
            payload.put("payment", payment);
            if (method != null && !method.isBlank() && !Set.of("credit_card", "debit_card", "pix", "boleto").contains(method)) {
                details.add(oneDetail("payment.method", "Invalid payment method"));
            }
        }
        payload.keySet().retainAll(Set.of("customerId", "addressId", "items", "payment"));
        if (!details.isEmpty()) throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
    }

    private static Map<String, Object> validateAddress(List<Map<String, String>> details, Object value) {
        if (!(value instanceof Map<?, ?> raw)) {
            details.add(oneDetail("address", "Required object"));
            return new HashMap<>();
        }
        var address = castMap(raw);
        address.put("label", required(details, "address.label", address.get("label")));
        address.put("street", required(details, "address.street", address.get("street")));
        address.put("number", required(details, "address.number", address.get("number")));
        address.put("complement", optionalString(details, "address.complement", address.get("complement")));
        address.put("district", required(details, "address.district", address.get("district")));
        address.put("city", required(details, "address.city", address.get("city")));
        address.put("state", required(details, "address.state", address.get("state")));
        address.put("postalCode", required(details, "address.postalCode", address.get("postalCode")));
        if (!(address.get("isDefault") instanceof Boolean)) details.add(oneDetail("address.isDefault", "Required boolean"));
        var state = string(address, "state");
        if (state != null && !state.isEmpty() && !state.matches("[A-Za-z]{2}")) {
            details.add(oneDetail("address.state", "Must contain exactly 2 ASCII letters"));
        } else if (state != null && !state.isEmpty()) {
            address.put("state", state.toUpperCase(Locale.ROOT));
        }
        address.keySet().retainAll(Set.of("label", "street", "number", "complement", "district", "city", "state", "postalCode", "isDefault"));
        return address;
    }

    private static boolean method(HttpExchange exchange, String method) throws IOException {
        if (!exchange.getRequestMethod().equals(method)) {
            writeError(exchange, new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed"));
            return false;
        }
        return true;
    }

    private static int pathId(String path, String prefix) {
        return positiveInt(path.substring(prefix.length()), "id");
    }

    private static boolean isEntityPath(String path, String prefix) {
        if (!path.startsWith(prefix) || path.length() == prefix.length()) return false;
        return !path.substring(prefix.length()).contains("/");
    }

    private static int positiveInt(String value, String field) {
        try {
            if (value == null || !value.matches("[0-9]+")) throw new NumberFormatException();
            var parsed = Integer.parseInt(value);
            if (parsed > 0) return parsed;
        } catch (Exception ignored) {
        }
        throw new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", detail(field, "Must be a positive integer"));
    }

    private static Map<String, String> query(HttpExchange exchange) {
        var result = new HashMap<String, String>();
        var query = exchange.getRequestURI().getRawQuery();
        if (query == null || query.isBlank()) return result;
        for (var part : query.split("&")) {
            var bits = part.split("=", 2);
            var key = URLDecoder.decode(bits[0], StandardCharsets.UTF_8);
            var value = URLDecoder.decode(bits.length > 1 ? bits[1] : "", StandardCharsets.UTF_8);
            result.put(key, value);
        }
        return result;
    }

    private static String jdbcUrl() {
        var direct = System.getenv("DATABASE_URL");
        if (direct != null && !direct.isBlank()) return direct.replace("postgresql://", "jdbc:postgresql://");
        return "jdbc:postgresql://" + env("POSTGRES_HOST", "localhost") + ":" + env("POSTGRES_PORT", "5432") + "/" + env("POSTGRES_DB", "benchmark_db");
    }

    private static String env(String key, String fallback) {
        var value = System.getenv(key);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static int intEnv(String key, int fallback) {
        try {
            return Integer.parseInt(env(key, String.valueOf(fallback)));
        } catch (Exception error) {
            return fallback;
        }
    }

    private static String required(List<Map<String, String>> details, String field, Object value) {
        if (!(value instanceof String text) || text.isBlank()) {
            details.add(oneDetail(field, "Required non-empty string"));
            return "";
        }
        return text.trim();
    }

    private static String optionalString(List<Map<String, String>> details, String field, Object value) {
        if (value == null) return null;
        if (!(value instanceof String text)) {
            details.add(oneDetail(field, "Must be a string or null"));
            return null;
        }
        return text.trim();
    }

    private static String string(Map<String, Object> map, String key) {
        var value = map.get(key);
        return value instanceof String text ? text : null;
    }

    private static int normalizedNumber(Object value, String field, List<Map<String, String>> details) {
        var map = new HashMap<String, Object>();
        map.put("value", value);
        var parsed = number(map, "value");
        if (parsed <= 0) details.add(oneDetail(field, "Must be a positive integer"));
        return Math.max(parsed, 0);
    }

    private static int number(Map<String, Object> map, String key) {
        var value = map.get(key);
        if (!(value instanceof Number number)) return -1;
        try {
            var decimal = new BigDecimal(number.toString()).stripTrailingZeros();
            if (decimal.scale() > 0 || decimal.compareTo(BigDecimal.ONE) < 0 || decimal.compareTo(BigDecimal.valueOf(Integer.MAX_VALUE)) > 0) return -1;
            return decimal.intValueExact();
        } catch (ArithmeticException error) {
            return -1;
        }
    }

    private static boolean bool(Map<String, Object> map, String key) {
        return Boolean.TRUE.equals(map.get(key));
    }

    private static Map<String, Object> object(Map<String, Object> map, String key) {
        var value = map.get(key);
        return value instanceof Map<?, ?> raw ? castMap(raw) : new HashMap<>();
    }

    private static List<Map<String, Object>> list(Map<String, Object> map, String key) {
        var value = map.get(key);
        if (!(value instanceof List<?> raw)) return List.of();
        var result = new ArrayList<Map<String, Object>>();
        for (var item : raw) if (item instanceof Map<?, ?> rawMap) result.add(castMap(rawMap));
        return result;
    }

    private static Map<String, Object> castMap(Map<?, ?> raw) {
        var result = new HashMap<String, Object>();
        for (var entry : raw.entrySet()) result.put(String.valueOf(entry.getKey()), entry.getValue());
        return result;
    }

    private static String money(BigDecimal value) {
        return value.setScale(2).toPlainString();
    }

    private static String instant(Timestamp value) {
        return value == null ? null : INSTANT.format(value.toInstant().truncatedTo(ChronoUnit.SECONDS).atOffset(ZoneOffset.UTC));
    }

    private static Map<String, String> oneDetail(String field, String message) {
        return Map.of("field", field, "message", message);
    }

    private static List<Map<String, String>> detail(String field, String message) {
        return List.of(oneDetail(field, message));
    }

    private static Map<String, Object> mapOf(Object... values) {
        var result = new LinkedHashMap<String, Object>();
        for (var i = 0; i < values.length; i += 2) result.put(String.valueOf(values[i]), values[i + 1]);
        return result;
    }

    private static void write(HttpExchange exchange, int status, Object body) throws IOException {
        var bytes = JSON.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    private static void writeError(HttpExchange exchange, ApiError error) throws IOException {
        write(exchange, error.status, mapOf("error", mapOf("code", error.code, "message", error.message, "details", error.details)));
    }

    private static ApiError serverError(Exception error) {
        for (Throwable current = error; current != null; current = current.getCause()) {
            if (current instanceof SQLException) {
                return new ApiError(500, "DATABASE_ERROR", "Database error");
            }
        }
        return new ApiError(500, "INTERNAL_ERROR", "Internal server error");
    }

    private static final class ApiError extends RuntimeException {
        final int status;
        final String code;
        final String message;
        final List<Map<String, String>> details;

        ApiError(int status, String code, String message) {
            this(status, code, message, List.of());
        }

        ApiError(int status, String code, String message, List<Map<String, String>> details) {
            super(message);
            this.status = status;
            this.code = code;
            this.message = message;
            this.details = details;
        }
    }

    private static final String GET_CUSTOMER = """
        SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
               a.id AS address_id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
        FROM customers c
        LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
        WHERE c.id = ?
        """;

    private static final String LIST_CUSTOMERS = """
        SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
               a.id AS address_id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
        FROM customers c
        LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
        ORDER BY c.created_at, c.id
        LIMIT ? OFFSET ?
        """;

    private static final String LIST_PRODUCTS = "SELECT id, category_id, sku, name, unit_price, stock_quantity, active FROM products WHERE category_id = ? AND active = true ORDER BY id";
    private static final String INSERT_CUSTOMER = "INSERT INTO customers (full_name, email, document_number, phone, status) VALUES (?, ?, ?, ?, 'active') RETURNING id";
    private static final String INSERT_ADDRESS = "INSERT INTO addresses (customer_id, label, street, number, complement, district, city, state, postal_code, is_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
    private static final String UPDATE_CUSTOMER = "UPDATE customers SET full_name = ?, phone = ?, status = ?, updated_at = now() WHERE id = ?";
    private static final String UPDATE_ADDRESS = "UPDATE addresses SET label = ?, street = ?, number = ?, complement = ?, district = ?, city = ?, state = ?, postal_code = ?, is_default = ? WHERE customer_id = ? AND is_default = true";

    private static final String GET_ORDER = """
        SELECT o.id AS order_id, o.status AS order_status, o.total_amount, o.created_at AS order_created_at, o.updated_at AS order_updated_at,
               c.id AS customer_id, c.full_name, c.email, c.document_number, c.phone, c.status AS customer_status, c.created_at AS customer_created_at, c.updated_at AS customer_updated_at,
               a.id AS address_id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default,
               oi.id AS item_id, oi.quantity, oi.unit_price AS item_unit_price, oi.total_price AS item_total_price,
               p.id AS product_id, p.sku, p.name AS product_name, p.unit_price AS product_unit_price, p.stock_quantity, p.active,
               cat.id AS category_id, cat.name AS category_name,
               pay.id AS payment_id, pay.method AS payment_method, pay.status AS payment_status, pay.amount AS payment_amount, pay.paid_at
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN addresses a ON a.id = o.address_id
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id
        JOIN categories cat ON cat.id = p.category_id
        JOIN payments pay ON pay.order_id = o.id
        WHERE o.id = ?
        ORDER BY oi.id
        """;
}
