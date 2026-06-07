import { ApiError } from "./errors.js";
import * as queries from "./queries.js";
import { customerFromRow, orderFromRows, productFromRow } from "./serializers.js";

async function fetchCustomer(client, customerId) {
  const result = await client.query(queries.GET_CUSTOMER, [customerId]);
  if (result.rowCount === 0) {
    return null;
  }
  return customerFromRow(result.rows[0]);
}

export async function getCustomer(pool, customerId) {
  const client = await pool.connect();
  try {
    const customer = await fetchCustomer(client, customerId);
    if (!customer) {
      throw new ApiError(404, "NOT_FOUND", "Customer not found");
    }
    return customer;
  } finally {
    client.release();
  }
}

export async function listCustomers(pool, page, pageSize) {
  const client = await pool.connect();
  try {
    const offset = (page - 1) * pageSize;
    const total = await client.query(queries.COUNT_CUSTOMERS);
    const rows = await client.query(queries.LIST_CUSTOMERS, [pageSize, offset]);
    return {
      page,
      pageSize,
      total: total.rows[0].total,
      items: rows.rows.map(customerFromRow)
    };
  } finally {
    client.release();
  }
}

export async function createCustomer(pool, payload) {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const inserted = await client.query(queries.INSERT_CUSTOMER, [
      payload.fullName,
      payload.email,
      payload.documentNumber,
      payload.phone
    ]);
    const customerId = inserted.rows[0].id;
    const address = payload.address;
    await client.query(queries.INSERT_ADDRESS, [
      customerId,
      address.label,
      address.street,
      address.number,
      address.complement,
      address.district,
      address.city,
      address.state,
      address.postalCode,
      address.isDefault
    ]);
    await client.query(queries.INSERT_AUDIT_LOG, [
      "customer",
      customerId,
      "create_customer",
      JSON.stringify(payload)
    ]);
    const customer = await fetchCustomer(client, customerId);
    await client.query("COMMIT");
    return customer;
  } catch (error) {
    await client.query("ROLLBACK");
    if (error.code === "23505") {
      throw new ApiError(409, "CONFLICT", "Customer email or document already exists");
    }
    throw error;
  } finally {
    client.release();
  }
}

export async function updateCustomer(pool, customerId, payload) {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const updated = await client.query(queries.UPDATE_CUSTOMER, [
      payload.fullName,
      payload.phone,
      payload.status,
      customerId
    ]);
    if (updated.rowCount === 0) {
      throw new ApiError(404, "NOT_FOUND", "Customer not found");
    }

    const address = payload.address;
    const changedAddress = await client.query(queries.UPDATE_DEFAULT_ADDRESS, [
      address.label,
      address.street,
      address.number,
      address.complement,
      address.district,
      address.city,
      address.state,
      address.postalCode,
      address.isDefault,
      customerId
    ]);
    if (changedAddress.rowCount === 0) {
      await client.query(queries.INSERT_ADDRESS, [
        customerId,
        address.label,
        address.street,
        address.number,
        address.complement,
        address.district,
        address.city,
        address.state,
        address.postalCode,
        address.isDefault
      ]);
    }

    await client.query(queries.INSERT_AUDIT_LOG, [
      "customer",
      customerId,
      "update_customer",
      JSON.stringify(payload)
    ]);
    const customer = await fetchCustomer(client, customerId);
    await client.query("COMMIT");
    return customer;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function listProducts(pool, categoryId) {
  const client = await pool.connect();
  try {
    const category = await client.query(queries.CATEGORY_EXISTS, [categoryId]);
    if (category.rowCount === 0) {
      throw new ApiError(404, "NOT_FOUND", "Category not found");
    }
    const products = await client.query(queries.LIST_PRODUCTS_BY_CATEGORY, [categoryId]);
    return {
      categoryId,
      items: products.rows.map(productFromRow)
    };
  } finally {
    client.release();
  }
}

async function fetchOrder(client, orderId) {
  const result = await client.query(queries.GET_ORDER, [orderId]);
  return orderFromRows(result.rows);
}

export async function getOrder(pool, orderId) {
  const client = await pool.connect();
  try {
    const order = await fetchOrder(client, orderId);
    if (!order) {
      throw new ApiError(404, "NOT_FOUND", "Order not found");
    }
    return order;
  } finally {
    client.release();
  }
}

export async function createOrder(pool, payload) {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const customer = await client.query(queries.ACTIVE_CUSTOMER_EXISTS, [payload.customerId]);
    if (customer.rowCount === 0) {
      throw new ApiError(404, "NOT_FOUND", "Customer not found");
    }
    const address = await client.query(queries.ADDRESS_BELONGS_TO_CUSTOMER, [
      payload.addressId,
      payload.customerId
    ]);
    if (address.rowCount === 0) {
      throw new ApiError(404, "NOT_FOUND", "Address not found");
    }

    const inserted = await client.query(queries.INSERT_ORDER, [payload.customerId, payload.addressId]);
    const orderId = inserted.rows[0].id;

    for (const item of payload.items) {
      const product = await client.query(queries.LOCK_PRODUCT, [item.productId]);
      if (product.rowCount === 0) {
        throw new ApiError(404, "NOT_FOUND", "Product not found");
      }
      const productRow = product.rows[0];
      if (productRow.stock_quantity < item.quantity) {
        throw new ApiError(409, "CONFLICT", "Insufficient stock");
      }
      const stock = await client.query(queries.UPDATE_PRODUCT_STOCK, [
        item.quantity,
        item.productId,
        item.quantity
      ]);
      if (stock.rowCount === 0) {
        throw new ApiError(409, "CONFLICT", "Insufficient stock");
      }
      await client.query(queries.INSERT_ORDER_ITEM, [
        orderId,
        item.productId,
        item.quantity,
        productRow.unit_price
      ]);
    }

    const total = await client.query(queries.UPDATE_ORDER_TOTAL, [orderId, orderId]);
    await client.query(queries.INSERT_PAYMENT, [
      orderId,
      payload.payment.method,
      total.rows[0].total_amount
    ]);
    await client.query(queries.INSERT_AUDIT_LOG, [
      "order",
      orderId,
      "create_order",
      JSON.stringify(payload)
    ]);

    const order = await fetchOrder(client, orderId);
    await client.query("COMMIT");
    return order;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
