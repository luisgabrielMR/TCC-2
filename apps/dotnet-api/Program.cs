using System.Data;
using System.Text.Json;
using System.Text.Json.Serialization;
using Npgsql;
using NpgsqlTypes;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://0.0.0.0:8000");
builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = null;
});

var settings = Settings.Load();
var dataSourceBuilder = new NpgsqlDataSourceBuilder(settings.ConnectionString);
await using var dataSource = dataSourceBuilder.Build();

var app = builder.Build();

app.Use(async (context, next) =>
{
    if (context.Request.Path.Value is { Length: > 1 } path && path.EndsWith('/'))
    {
        await Error(new ApiError(404, "NOT_FOUND", "Route not found")).ExecuteAsync(context);
        return;
    }
    try
    {
        await next();
    }
    catch (NpgsqlException)
    {
        if (!context.Response.HasStarted)
        {
            await Error(new ApiError(500, "DATABASE_ERROR", "Database error")).ExecuteAsync(context);
            return;
        }
        throw;
    }
    catch (Exception)
    {
        if (!context.Response.HasStarted)
        {
            await Error(new ApiError(500, "INTERNAL_ERROR", "Internal server error")).ExecuteAsync(context);
            return;
        }
        throw;
    }
});

app.UseStatusCodePages(async statusContext =>
{
    var status = statusContext.HttpContext.Response.StatusCode;
    if (status is not (StatusCodes.Status404NotFound or StatusCodes.Status405MethodNotAllowed)) return;
    var error = status == StatusCodes.Status405MethodNotAllowed
        ? new ApiError(405, "METHOD_NOT_ALLOWED", "Method not allowed")
        : new ApiError(404, "NOT_FOUND", "Route not found");
    await Error(error).ExecuteAsync(statusContext.HttpContext);
});

app.MapGet("/health", () => Results.Json(new Dictionary<string, object?> { ["status"] = "ok" }));

app.MapGet("/customers", async (HttpRequest request) =>
{
    var parsed = ParsePagination(request);
    if (parsed.Error is not null) return Error(parsed.Error);

    await using var conn = await dataSource.OpenConnectionAsync();
    var totalCmd = new NpgsqlCommand("SELECT count(*)::int FROM customers", conn);
    var total = (int)(await totalCmd.ExecuteScalarAsync() ?? 0);

    await using var cmd = new NpgsqlCommand(Sql.ListCustomers, conn);
    cmd.Parameters.AddWithValue("limit", parsed.PageSize);
    cmd.Parameters.AddWithValue("offset", (long)(parsed.Page - 1) * parsed.PageSize);
    await using var reader = await cmd.ExecuteReaderAsync();
    var items = new List<Dictionary<string, object?>>();
    while (await reader.ReadAsync())
    {
        items.Add(CustomerFromReader(reader));
    }

    return Results.Json(new Dictionary<string, object?>
    {
        ["page"] = parsed.Page,
        ["pageSize"] = parsed.PageSize,
        ["total"] = total,
        ["items"] = items
    });
});

app.MapGet("/customers/{id}", async (string id) =>
{
    var parsed = PositiveInt(id, "id");
    if (parsed.Error is not null) return Error(parsed.Error);
    var customer = await FetchCustomerFromDataSource(dataSource, parsed.Value);
    return customer is null ? Error(NotFound("Customer not found")) : Results.Json(customer);
});

app.MapPost("/customers", async (HttpRequest request) =>
{
    var json = await ReadJson(request);
    if (json.Error is not null) return Error(json.Error);
    var body = ValidateCreateCustomer(json.Value);
    if (body.Error is not null) return Error(body.Error);

    await using var conn = await dataSource.OpenConnectionAsync();
    await using var tx = await conn.BeginTransactionAsync();
    try
    {
        await using var insertCustomer = new NpgsqlCommand(Sql.InsertCustomer, conn, tx);
        insertCustomer.Parameters.AddWithValue("fullName", body.Value!.FullName!);
        insertCustomer.Parameters.AddWithValue("email", body.Value.Email!);
        insertCustomer.Parameters.AddWithValue("documentNumber", body.Value.DocumentNumber!);
        insertCustomer.Parameters.AddWithValue("phone", (object?)body.Value.Phone ?? DBNull.Value);
        var customerId = Convert.ToInt32(await insertCustomer.ExecuteScalarAsync());

        await InsertAddress(conn, tx, customerId, body.Value.Address!);
        await InsertAudit(conn, tx, "customer", customerId, "create_customer", body.Value);
        var customer = await FetchCustomerFromConnection(conn, tx, customerId);
        await tx.CommitAsync();
        return Results.Json(customer, statusCode: StatusCodes.Status201Created);
    }
    catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
    {
        await tx.RollbackAsync();
        return Error(new ApiError(409, "CONFLICT", "Customer email or document already exists"));
    }
    catch
    {
        await tx.RollbackAsync();
        throw;
    }
});

app.MapPut("/customers/{id}", async (string id, HttpRequest request) =>
{
    var parsed = PositiveInt(id, "id");
    if (parsed.Error is not null) return Error(parsed.Error);
    var json = await ReadJson(request);
    if (json.Error is not null) return Error(json.Error);
    var body = ValidateUpdateCustomer(json.Value);
    if (body.Error is not null) return Error(body.Error);

    await using var conn = await dataSource.OpenConnectionAsync();
    await using var tx = await conn.BeginTransactionAsync();
    try
    {
        await using var update = new NpgsqlCommand(Sql.UpdateCustomer, conn, tx);
        update.Parameters.AddWithValue("fullName", body.Value!.FullName!);
        update.Parameters.AddWithValue("phone", (object?)body.Value.Phone ?? DBNull.Value);
        update.Parameters.AddWithValue("status", body.Value.Status!);
        update.Parameters.AddWithValue("id", parsed.Value);
        var changed = await update.ExecuteNonQueryAsync();
        if (changed == 0)
        {
            await tx.RollbackAsync();
            return Error(NotFound("Customer not found"));
        }

        await using var updateAddress = new NpgsqlCommand(Sql.UpdateAddress, conn, tx);
        AddAddressParameters(updateAddress, body.Value.Address!);
        updateAddress.Parameters.AddWithValue("customerId", parsed.Value);
        var changedAddress = await updateAddress.ExecuteNonQueryAsync();
        if (changedAddress == 0) await InsertAddress(conn, tx, parsed.Value, body.Value.Address!);
        await InsertAudit(conn, tx, "customer", parsed.Value, "update_customer", body.Value);
        var customer = await FetchCustomerFromConnection(conn, tx, parsed.Value);
        await tx.CommitAsync();
        return Results.Json(customer);
    }
    catch
    {
        await tx.RollbackAsync();
        throw;
    }
});

app.MapGet("/products", async (HttpRequest request) =>
{
    var parsed = PositiveInt(request.Query["categoryId"].ToString(), "categoryId");
    if (parsed.Error is not null) return Error(parsed.Error);

    await using var conn = await dataSource.OpenConnectionAsync();
    await using var categoryCmd = new NpgsqlCommand("SELECT id FROM categories WHERE id = @id", conn);
    categoryCmd.Parameters.AddWithValue("id", parsed.Value);
    if (await categoryCmd.ExecuteScalarAsync() is null) return Error(NotFound("Category not found"));

    await using var cmd = new NpgsqlCommand(Sql.ListProducts, conn);
    cmd.Parameters.AddWithValue("categoryId", parsed.Value);
    await using var reader = await cmd.ExecuteReaderAsync();
    var items = new List<Dictionary<string, object?>>();
    while (await reader.ReadAsync())
    {
        items.Add(new Dictionary<string, object?>
        {
            ["id"] = reader.GetInt64(0),
            ["categoryId"] = reader.GetInt64(1),
            ["sku"] = reader.GetString(2),
            ["name"] = reader.GetString(3),
            ["unitPrice"] = Money(reader.GetDecimal(4)),
            ["stockQuantity"] = reader.GetInt32(5),
            ["active"] = reader.GetBoolean(6)
        });
    }
    return Results.Json(new Dictionary<string, object?> { ["categoryId"] = parsed.Value, ["items"] = items });
});

app.MapPost("/orders", async (HttpRequest request) =>
{
    var json = await ReadJson(request);
    if (json.Error is not null) return Error(json.Error);
    var body = ValidateCreateOrder(json.Value);
    if (body.Error is not null) return Error(body.Error);

    await using var conn = await dataSource.OpenConnectionAsync();
    await using var tx = await conn.BeginTransactionAsync();
    try
    {
        var customerExists = await ScalarExists(conn, tx, "SELECT id FROM customers WHERE id = @id AND status = 'active'", ("id", body.Value!.CustomerId.Value));
        if (!customerExists)
        {
            await tx.RollbackAsync();
            return Error(NotFound("Customer not found"));
        }
        var addressExists = await ScalarExists(conn, tx, "SELECT id FROM addresses WHERE id = @id AND customer_id = @customerId", ("id", body.Value.AddressId.Value), ("customerId", body.Value.CustomerId.Value));
        if (!addressExists)
        {
            await tx.RollbackAsync();
            return Error(NotFound("Address not found"));
        }

        await using var insertOrder = new NpgsqlCommand("INSERT INTO orders (customer_id, address_id, status, total_amount) VALUES (@customerId, @addressId, 'created', 0) RETURNING id", conn, tx);
        insertOrder.Parameters.AddWithValue("customerId", body.Value.CustomerId.Value);
        insertOrder.Parameters.AddWithValue("addressId", body.Value.AddressId.Value);
        var orderId = Convert.ToInt32(await insertOrder.ExecuteScalarAsync());

        foreach (var item in body.Value.Items!)
        {
            await using var lockProduct = new NpgsqlCommand("SELECT id, unit_price, stock_quantity FROM products WHERE id = @id AND active = true FOR UPDATE", conn, tx);
            lockProduct.Parameters.AddWithValue("id", item.ProductId.Value);
            await using var reader = await lockProduct.ExecuteReaderAsync();
            if (!await reader.ReadAsync())
            {
                await reader.DisposeAsync();
                await tx.RollbackAsync();
                return Error(NotFound("Product not found"));
            }
            var price = reader.GetDecimal(1);
            var stock = reader.GetInt32(2);
            await reader.DisposeAsync();
            if (stock < item.Quantity.Value)
            {
                await tx.RollbackAsync();
                return Error(new ApiError(409, "CONFLICT", "Insufficient stock"));
            }

            await using var stockCmd = new NpgsqlCommand("UPDATE products SET stock_quantity = stock_quantity - @quantity WHERE id = @id AND stock_quantity >= @quantity", conn, tx);
            stockCmd.Parameters.AddWithValue("quantity", item.Quantity.Value);
            stockCmd.Parameters.AddWithValue("id", item.ProductId.Value);
            if (await stockCmd.ExecuteNonQueryAsync() == 0)
            {
                await tx.RollbackAsync();
                return Error(new ApiError(409, "CONFLICT", "Insufficient stock"));
            }

            await using var insertItem = new NpgsqlCommand("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (@orderId, @productId, @quantity, @price)", conn, tx);
            insertItem.Parameters.AddWithValue("orderId", orderId);
            insertItem.Parameters.AddWithValue("productId", item.ProductId.Value);
            insertItem.Parameters.AddWithValue("quantity", item.Quantity.Value);
            insertItem.Parameters.AddWithValue("price", price);
            await insertItem.ExecuteNonQueryAsync();
        }

        await using var totalCmd = new NpgsqlCommand("UPDATE orders SET total_amount = (SELECT sum(total_price)::numeric(12, 2) FROM order_items WHERE order_id = @id), status = 'paid', updated_at = now() WHERE id = @id RETURNING total_amount", conn, tx);
        totalCmd.Parameters.AddWithValue("id", orderId);
        var total = (decimal)(await totalCmd.ExecuteScalarAsync() ?? 0m);

        await using var paymentCmd = new NpgsqlCommand("INSERT INTO payments (order_id, method, status, amount, paid_at) VALUES (@orderId, @method, 'paid', @amount, now())", conn, tx);
        paymentCmd.Parameters.AddWithValue("orderId", orderId);
        paymentCmd.Parameters.AddWithValue("method", body.Value.Payment!.Method!);
        paymentCmd.Parameters.AddWithValue("amount", total);
        await paymentCmd.ExecuteNonQueryAsync();

        await InsertAudit(conn, tx, "order", orderId, "create_order", body.Value);
        var order = await FetchOrderFromConnection(conn, tx, orderId);
        await tx.CommitAsync();
        return Results.Json(order, statusCode: StatusCodes.Status201Created);
    }
    catch
    {
        await tx.RollbackAsync();
        throw;
    }
});

app.MapGet("/orders/{id}", async (string id) =>
{
    var parsed = PositiveInt(id, "id");
    if (parsed.Error is not null) return Error(parsed.Error);
    var order = await FetchOrderFromDataSource(dataSource, parsed.Value);
    return order is null ? Error(NotFound("Order not found")) : Results.Json(order);
});

app.Run();

static async Task<Dictionary<string, object?>?> FetchCustomerFromDataSource(NpgsqlDataSource ds, int id)
{
    await using var conn = await ds.OpenConnectionAsync();
    return await FetchCustomerFromConnection(conn, null, id);
}

static async Task<Dictionary<string, object?>?> FetchCustomerFromConnection(NpgsqlConnection conn, NpgsqlTransaction? tx, int id)
{
    await using var cmd = new NpgsqlCommand(Sql.GetCustomer, conn, tx);
    cmd.Parameters.AddWithValue("id", id);
    await using var reader = await cmd.ExecuteReaderAsync();
    if (!await reader.ReadAsync()) return null;
    return CustomerFromReader(reader);
}

static Dictionary<string, object?> CustomerFromReader(NpgsqlDataReader reader)
{
    return new Dictionary<string, object?>
    {
        ["id"] = reader.GetInt64(0),
        ["fullName"] = reader.GetString(1),
        ["email"] = reader.GetString(2),
        ["documentNumber"] = reader.GetString(3),
        ["phone"] = DbNull(reader, 4) ? null : reader.GetString(4),
        ["status"] = reader.GetString(5),
        ["address"] = AddressFromReader(reader),
        ["createdAt"] = Instant(reader.GetDateTime(6)),
        ["updatedAt"] = Instant(reader.GetDateTime(7))
    };
}

static Dictionary<string, object?>? AddressFromReader(NpgsqlDataReader reader)
{
    if (DbNull(reader, 8)) return null;
    return new Dictionary<string, object?>
    {
        ["id"] = reader.GetInt64(8),
        ["label"] = reader.GetString(9),
        ["street"] = reader.GetString(10),
        ["number"] = reader.GetString(11),
        ["complement"] = DbNull(reader, 12) ? null : reader.GetString(12),
        ["district"] = reader.GetString(13),
        ["city"] = reader.GetString(14),
        ["state"] = reader.GetString(15),
        ["postalCode"] = reader.GetString(16),
        ["isDefault"] = reader.GetBoolean(17)
    };
}

static async Task<Dictionary<string, object?>?> FetchOrderFromDataSource(NpgsqlDataSource ds, int id)
{
    await using var conn = await ds.OpenConnectionAsync();
    return await FetchOrderFromConnection(conn, null, id);
}

static async Task<Dictionary<string, object?>?> FetchOrderFromConnection(NpgsqlConnection conn, NpgsqlTransaction? tx, int id)
{
    await using var cmd = new NpgsqlCommand(Sql.GetOrder, conn, tx);
    cmd.Parameters.AddWithValue("id", id);
    await using var reader = await cmd.ExecuteReaderAsync();
    Dictionary<string, object?>? order = null;
    var items = new List<Dictionary<string, object?>>();
    while (await reader.ReadAsync())
    {
        var address = new Dictionary<string, object?>
        {
            ["id"] = reader.GetInt64(13),
            ["label"] = reader.GetString(14),
            ["street"] = reader.GetString(15),
            ["number"] = reader.GetString(16),
            ["complement"] = DbNull(reader, 17) ? null : reader.GetString(17),
            ["district"] = reader.GetString(18),
            ["city"] = reader.GetString(19),
            ["state"] = reader.GetString(20),
            ["postalCode"] = reader.GetString(21),
            ["isDefault"] = reader.GetBoolean(22)
        };
        order ??= new Dictionary<string, object?>
        {
            ["id"] = reader.GetInt64(0),
            ["status"] = reader.GetString(1),
            ["totalAmount"] = Money(reader.GetDecimal(2)),
            ["customer"] = new Dictionary<string, object?>
            {
                ["id"] = reader.GetInt64(5),
                ["fullName"] = reader.GetString(6),
                ["email"] = reader.GetString(7),
                ["documentNumber"] = reader.GetString(8),
                ["phone"] = DbNull(reader, 9) ? null : reader.GetString(9),
                ["status"] = reader.GetString(10),
                ["address"] = address,
                ["createdAt"] = Instant(reader.GetDateTime(11)),
                ["updatedAt"] = Instant(reader.GetDateTime(12))
            },
            ["address"] = address,
            ["items"] = items,
            ["payment"] = new Dictionary<string, object?>
            {
                ["id"] = reader.GetInt64(35),
                ["method"] = reader.GetString(36),
                ["status"] = reader.GetString(37),
                ["amount"] = Money(reader.GetDecimal(38)),
                ["paidAt"] = DbNull(reader, 39) ? null : Instant(reader.GetDateTime(39))
            },
            ["createdAt"] = Instant(reader.GetDateTime(3)),
            ["updatedAt"] = Instant(reader.GetDateTime(4))
        };
        items.Add(new Dictionary<string, object?>
        {
            ["id"] = reader.GetInt64(23),
            ["quantity"] = reader.GetInt32(24),
            ["unitPrice"] = Money(reader.GetDecimal(25)),
            ["totalPrice"] = Money(reader.GetDecimal(26)),
            ["product"] = new Dictionary<string, object?>
            {
                ["id"] = reader.GetInt64(27),
                ["categoryId"] = reader.GetInt64(33),
                ["categoryName"] = reader.GetString(34),
                ["sku"] = reader.GetString(28),
                ["name"] = reader.GetString(29),
                ["unitPrice"] = Money(reader.GetDecimal(30)),
                ["stockQuantity"] = reader.GetInt32(31),
                ["active"] = reader.GetBoolean(32)
            }
        });
    }
    return order;
}

static async Task InsertAddress(NpgsqlConnection conn, NpgsqlTransaction tx, int customerId, AddressInput address)
{
    await using var cmd = new NpgsqlCommand(Sql.InsertAddress, conn, tx);
    AddAddressParameters(cmd, address);
    cmd.Parameters.AddWithValue("customerId", customerId);
    await cmd.ExecuteNonQueryAsync();
}

static void AddAddressParameters(NpgsqlCommand cmd, AddressInput address)
{
    cmd.Parameters.AddWithValue("label", address.Label!);
    cmd.Parameters.AddWithValue("street", address.Street!);
    cmd.Parameters.AddWithValue("number", address.Number!);
    cmd.Parameters.AddWithValue("complement", (object?)address.Complement ?? DBNull.Value);
    cmd.Parameters.AddWithValue("district", address.District!);
    cmd.Parameters.AddWithValue("city", address.City!);
    cmd.Parameters.AddWithValue("state", address.State!);
    cmd.Parameters.AddWithValue("postalCode", address.PostalCode!);
    cmd.Parameters.AddWithValue("isDefault", address.IsDefault!.Value);
}

static async Task InsertAudit(NpgsqlConnection conn, NpgsqlTransaction tx, string entityType, int entityId, string action, object payload)
{
    await using var cmd = new NpgsqlCommand("INSERT INTO audit_logs (entity_type, entity_id, action, payload) VALUES (@entityType, @entityId, @action, @payload)", conn, tx);
    cmd.Parameters.AddWithValue("entityType", entityType);
    cmd.Parameters.AddWithValue("entityId", entityId);
    cmd.Parameters.AddWithValue("action", action);
    cmd.Parameters.Add("payload", NpgsqlDbType.Jsonb).Value = JsonSerializer.Serialize(payload, JsonDefaults.Audit);
    await cmd.ExecuteNonQueryAsync();
}

static async Task<bool> ScalarExists(NpgsqlConnection conn, NpgsqlTransaction tx, string sql, params (string Name, object Value)[] parameters)
{
    await using var cmd = new NpgsqlCommand(sql, conn, tx);
    foreach (var parameter in parameters) cmd.Parameters.AddWithValue(parameter.Name, parameter.Value);
    return await cmd.ExecuteScalarAsync() is not null;
}

static async Task<JsonObjectRead> ReadJson(HttpRequest request)
{
    try
    {
        using var document = await JsonDocument.ParseAsync(request.Body);
        var value = document.RootElement.Clone();
        return value.ValueKind == JsonValueKind.Object
            ? new JsonObjectRead(value, null)
            : new JsonObjectRead(default, new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", Detail("$", "Must be a JSON object")));
    }
    catch (JsonException)
    {
        return new JsonObjectRead(default, new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", Detail("$", "Invalid JSON")));
    }
}

static ValidationResult<CreateCustomerRequest> ValidateCreateCustomer(JsonElement raw)
{
    var details = new List<Dictionary<string, string>>();
    var request = new CreateCustomerRequest(
        RequiredString(raw, "fullName", "fullName", details),
        RequiredString(raw, "email", "email", details),
        RequiredString(raw, "documentNumber", "documentNumber", details),
        OptionalString(raw, "phone", "phone", details),
        ValidateAddress(raw, details)
    );
    if (request.Email is { Length: > 0 } && !request.Email.Contains('@')) details.Add(OneDetail("email", "Must be a valid email-like value"));
    return Validated(request, details);
}

static ValidationResult<UpdateCustomerRequest> ValidateUpdateCustomer(JsonElement raw)
{
    var details = new List<Dictionary<string, string>>();
    var fullName = RequiredString(raw, "fullName", "fullName", details);
    var status = RequiredString(raw, "status", "status", details);
    if (status.Length > 0 && status is not ("active" or "inactive")) details.Add(OneDetail("status", "Must be active or inactive"));
    var request = new UpdateCustomerRequest(
        fullName,
        OptionalString(raw, "phone", "phone", details),
        status,
        ValidateAddress(raw, details)
    );
    return Validated(request, details);
}

static ValidationResult<CreateOrderRequest> ValidateCreateOrder(JsonElement raw)
{
    var details = new List<Dictionary<string, string>>();
    var customerId = IntegerField(raw, "customerId", "customerId", details);
    var addressId = IntegerField(raw, "addressId", "addressId", details);
    var items = new List<OrderItemInput>();
    if (!raw.TryGetProperty("items", out var rawItems) || rawItems.ValueKind != JsonValueKind.Array || rawItems.GetArrayLength() == 0)
    {
        details.Add(OneDetail("items", "Must contain at least one item"));
    }
    else
    {
        var index = 0;
        foreach (var rawItem in rawItems.EnumerateArray())
        {
            if (rawItem.ValueKind != JsonValueKind.Object)
            {
                details.Add(OneDetail($"items[{index}]", "Must be an object"));
            }
            else
            {
                items.Add(new OrderItemInput(
                    IntegerField(rawItem, "productId", $"items[{index}].productId", details),
                    IntegerField(rawItem, "quantity", $"items[{index}].quantity", details)
                ));
            }
            index++;
        }
    }

    PaymentInput? payment = null;
    if (!raw.TryGetProperty("payment", out var rawPayment) || rawPayment.ValueKind != JsonValueKind.Object)
    {
        details.Add(OneDetail("payment", "Required object"));
    }
    else
    {
        var method = RequiredString(rawPayment, "method", "payment.method", details);
        payment = new PaymentInput(method);
        if (method.Length > 0 && method is not ("credit_card" or "debit_card" or "pix" or "boleto"))
        {
            details.Add(OneDetail("payment.method", "Invalid payment method"));
        }
    }

    return Validated(new CreateOrderRequest(customerId, addressId, items, payment), details);
}

static AddressInput? ValidateAddress(JsonElement raw, List<Dictionary<string, string>> details)
{
    if (!raw.TryGetProperty("address", out var address) || address.ValueKind != JsonValueKind.Object)
    {
        details.Add(OneDetail("address", "Required object"));
        return null;
    }
    bool? isDefault = null;
    if (address.TryGetProperty("isDefault", out var rawDefault) && rawDefault.ValueKind is JsonValueKind.True or JsonValueKind.False)
    {
        isDefault = rawDefault.GetBoolean();
    }
    var label = RequiredString(address, "label", "address.label", details);
    var street = RequiredString(address, "street", "address.street", details);
    var number = RequiredString(address, "number", "address.number", details);
    var complement = OptionalString(address, "complement", "address.complement", details);
    var district = RequiredString(address, "district", "address.district", details);
    var city = RequiredString(address, "city", "address.city", details);
    var state = RequiredString(address, "state", "address.state", details);
    if (!string.IsNullOrEmpty(state) && (state.Length != 2 || !state.All(character => character is >= 'A' and <= 'Z' or >= 'a' and <= 'z')))
    {
        details.Add(OneDetail("address.state", "Must contain exactly 2 ASCII letters"));
    }
    else if (!string.IsNullOrEmpty(state))
    {
        state = state.ToUpperInvariant();
    }
    var postalCode = RequiredString(address, "postalCode", "address.postalCode", details);
    var result = new AddressInput(
        label,
        street,
        number,
        complement,
        district,
        city,
        state,
        postalCode,
        isDefault
    );
    if (isDefault is null) details.Add(OneDetail("address.isDefault", "Required boolean"));
    return result;
}

static string RequiredString(JsonElement raw, string key, string field, List<Dictionary<string, string>> details)
{
    if (!raw.TryGetProperty(key, out var value) || value.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(value.GetString()))
    {
        details.Add(OneDetail(field, "Required non-empty string"));
        return "";
    }
    return value.GetString()!.Trim();
}

static string? OptionalString(JsonElement raw, string key, string field, List<Dictionary<string, string>> details)
{
    if (!raw.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null) return null;
    if (value.ValueKind != JsonValueKind.String)
    {
        details.Add(OneDetail(field, "Must be a string or null"));
        return null;
    }
    return value.GetString()!.Trim();
}

static IntegerInput IntegerField(JsonElement raw, string key, string field, List<Dictionary<string, string>> details)
{
    if (raw.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.Number &&
        value.TryGetDecimal(out var number) && number >= 1 && number <= int.MaxValue && decimal.Truncate(number) == number)
    {
        return new IntegerInput((int)number, true);
    }
    details.Add(OneDetail(field, "Must be a positive integer"));
    return new IntegerInput(0, false);
}

static ValidationResult<T> Validated<T>(T value, List<Dictionary<string, string>> details)
{
    return details.Count == 0
        ? new ValidationResult<T>(value, null)
        : new ValidationResult<T>(default, new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details));
}

static ParseResult PositiveInt(string value, string field)
{
    return value.Length > 0 && value.All(character => character is >= '0' and <= '9') && int.TryParse(value, out var parsed) && parsed > 0
        ? new ParseResult(parsed, null)
        : new ParseResult(0, new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", Detail(field, "Must be a positive integer")));
}

static PaginationResult ParsePagination(HttpRequest request)
{
    var page = PositiveInt(request.Query.ContainsKey("page") ? request.Query["page"].ToString() : "1", "page");
    if (page.Error is not null) return new PaginationResult(0, 0, page.Error);
    var pageSize = PositiveInt(request.Query.ContainsKey("pageSize") ? request.Query["pageSize"].ToString() : "50", "pageSize");
    if (pageSize.Error is not null) return new PaginationResult(0, 0, pageSize.Error);
    if (pageSize.Value > 100) return new PaginationResult(0, 0, new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", Detail("pageSize", "Must be between 1 and 100")));
    return new PaginationResult(page.Value, pageSize.Value, null);
}

static IResult Error(ApiError error)
{
    return Results.Json(new Dictionary<string, object?>
    {
        ["error"] = new Dictionary<string, object?>
        {
            ["code"] = error.Code,
            ["message"] = error.Message,
            ["details"] = error.Details ?? new List<Dictionary<string, string>>()
        }
    }, statusCode: error.Status);
}

static ApiError NotFound(string message) => new(404, "NOT_FOUND", message, new List<Dictionary<string, string>>());
static List<Dictionary<string, string>> Detail(string field, string message) => new() { OneDetail(field, message) };
static Dictionary<string, string> OneDetail(string field, string message) => new() { ["field"] = field, ["message"] = message };
static bool DbNull(NpgsqlDataReader reader, int ordinal) => reader.IsDBNull(ordinal);
static string Money(decimal value) => value.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture);
static string Instant(DateTime value) => value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");

static class Sql
{
public const string GetCustomer = """
SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
WHERE c.id = @id
""";

public const string ListCustomers = """
SELECT c.id, c.full_name, c.email, c.document_number, c.phone, c.status, c.created_at, c.updated_at,
       a.id, a.label, a.street, a.number, a.complement, a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
ORDER BY c.created_at, c.id
LIMIT @limit OFFSET @offset
""";

public const string InsertCustomer = """
INSERT INTO customers (full_name, email, document_number, phone, status)
VALUES (@fullName, @email, @documentNumber, @phone, 'active')
RETURNING id
""";

public const string InsertAddress = """
INSERT INTO addresses (customer_id, label, street, number, complement, district, city, state, postal_code, is_default)
VALUES (@customerId, @label, @street, @number, @complement, @district, @city, @state, @postalCode, @isDefault)
""";

public const string UpdateCustomer = """
UPDATE customers SET full_name = @fullName, phone = @phone, status = @status, updated_at = now()
WHERE id = @id
""";

public const string UpdateAddress = """
UPDATE addresses
SET label = @label, street = @street, number = @number, complement = @complement, district = @district, city = @city, state = @state, postal_code = @postalCode, is_default = @isDefault
WHERE customer_id = @customerId AND is_default = true
""";

public const string ListProducts = """
SELECT id, category_id, sku, name, unit_price, stock_quantity, active
FROM products
WHERE category_id = @categoryId AND active = true
ORDER BY id
""";

public const string GetOrder = """
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
WHERE o.id = @id
ORDER BY oi.id
""";
}

record Settings(string ConnectionString)
{
    public static Settings Load()
    {
        var direct = Environment.GetEnvironmentVariable("DATABASE_URL");
        var builder = direct is not null
            ? new NpgsqlConnectionStringBuilder(direct)
            : new NpgsqlConnectionStringBuilder
            {
                Host = Env("POSTGRES_HOST", "localhost"),
                Port = int.Parse(Env("POSTGRES_PORT", "5432")),
                Database = Env("POSTGRES_DB", "benchmark_db"),
                Username = Env("POSTGRES_USER", "benchmark_user"),
                Password = Env("POSTGRES_PASSWORD", "benchmark_password")
            };
        builder.Pooling = true;
        builder.MinPoolSize = IntEnv("DB_POOL_MIN", 1);
        builder.MaxPoolSize = IntEnv("DB_POOL_MAX", 20);
        builder.Timeout = IntEnv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10);
        builder.CommandTimeout = 0; // PostgreSQL enforces the shared statement timeout.
        builder.ConnectionIdleLifetime = IntEnv("DB_POOL_IDLE_TIMEOUT_SECONDS", 60);
        builder.ConnectionLifetime = IntEnv("DB_POOL_MAX_LIFETIME_SECONDS", 1800);
        return new Settings(builder.ConnectionString);
    }
    static string Env(string name, string fallback) => Environment.GetEnvironmentVariable(name) ?? fallback;
    static int IntEnv(string name, int fallback) => int.TryParse(Environment.GetEnvironmentVariable(name), out var value) ? value : fallback;
}

record ApiError(int Status, string Code, string Message, List<Dictionary<string, string>>? Details = null);
record ParseResult(int Value, ApiError? Error);
record PaginationResult(int Page, int PageSize, ApiError? Error);
record JsonObjectRead(JsonElement Value, ApiError? Error);
record ValidationResult<T>(T? Value, ApiError? Error);
record AddressInput(string? Label, string? Street, string? Number, string? Complement, string? District, string? City, string? State, string? PostalCode, bool? IsDefault);
record CreateCustomerRequest(string? FullName, string? Email, string? DocumentNumber, string? Phone, AddressInput? Address);
record UpdateCustomerRequest(string? FullName, string? Phone, string? Status, AddressInput? Address);
readonly record struct IntegerInput(int Value, bool Valid);

sealed class IntegerInputJsonConverter : JsonConverter<IntegerInput>
{
    public override IntegerInput Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Number && reader.TryGetDecimal(out var value) &&
            value >= 1 && value <= int.MaxValue && decimal.Truncate(value) == value)
        {
            return new IntegerInput((int)value, true);
        }
        if (reader.TokenType is JsonTokenType.StartArray or JsonTokenType.StartObject)
        {
            using var ignored = JsonDocument.ParseValue(ref reader);
        }
        return new IntegerInput(0, false);
    }

    public override void Write(Utf8JsonWriter writer, IntegerInput value, JsonSerializerOptions options) =>
        writer.WriteNumberValue(value.Value);
}

record OrderItemInput(
    [property: JsonConverter(typeof(IntegerInputJsonConverter))] IntegerInput ProductId,
    [property: JsonConverter(typeof(IntegerInputJsonConverter))] IntegerInput Quantity
);
record PaymentInput(string? Method);
record CreateOrderRequest(
    [property: JsonConverter(typeof(IntegerInputJsonConverter))] IntegerInput CustomerId,
    [property: JsonConverter(typeof(IntegerInputJsonConverter))] IntegerInput AddressId,
    List<OrderItemInput>? Items,
    PaymentInput? Payment
);

static class JsonDefaults
{
    public static readonly JsonSerializerOptions Audit = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };
}
