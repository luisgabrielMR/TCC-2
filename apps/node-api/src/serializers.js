function instant(value) {
  if (value === null || value === undefined) {
    return null;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  return new Date(value).toISOString();
}

function money(value) {
  return Number(value).toFixed(2);
}

export function addressFromRow(row) {
  if (row.address_id === null || row.address_id === undefined) {
    return null;
  }
  return {
    id: row.address_id,
    label: row.label,
    street: row.street,
    number: row.number,
    complement: row.complement,
    district: row.district,
    city: row.city,
    state: row.state,
    postalCode: row.postal_code,
    isDefault: row.is_default
  };
}

export function customerFromRow(row) {
  return {
    id: row.id,
    fullName: row.full_name,
    email: row.email,
    documentNumber: row.document_number,
    phone: row.phone,
    status: row.status,
    address: addressFromRow(row),
    createdAt: instant(row.created_at),
    updatedAt: instant(row.updated_at)
  };
}

export function productFromRow(row) {
  return {
    id: row.id,
    categoryId: row.category_id,
    sku: row.sku,
    name: row.name,
    unitPrice: money(row.unit_price),
    stockQuantity: row.stock_quantity,
    active: row.active
  };
}

export function orderFromRows(rows) {
  if (rows.length === 0) {
    return null;
  }

  const first = rows[0];
  return {
    id: first.order_id,
    status: first.order_status,
    totalAmount: money(first.total_amount),
    customer: {
      id: first.customer_id,
      fullName: first.full_name,
      email: first.email,
      documentNumber: first.document_number,
      phone: first.phone,
      status: first.customer_status,
      address: addressFromRow(first),
      createdAt: instant(first.customer_created_at),
      updatedAt: instant(first.customer_updated_at)
    },
    address: addressFromRow(first),
    items: rows.map((row) => ({
      id: row.item_id,
      quantity: row.quantity,
      unitPrice: money(row.item_unit_price),
      totalPrice: money(row.item_total_price),
      product: {
        id: row.product_id,
        categoryId: row.category_id,
        categoryName: row.category_name,
        sku: row.sku,
        name: row.product_name,
        unitPrice: money(row.product_unit_price),
        stockQuantity: row.stock_quantity,
        active: row.active
      }
    })),
    payment: {
      id: first.payment_id,
      method: first.payment_method,
      status: first.payment_status,
      amount: money(first.payment_amount),
      paidAt: instant(first.paid_at)
    },
    createdAt: instant(first.order_created_at),
    updatedAt: instant(first.order_updated_at)
  };
}
