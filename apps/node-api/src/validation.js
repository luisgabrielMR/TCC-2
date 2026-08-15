import { ApiError } from "./errors.js";

const VALID_STATUSES = new Set(["active", "inactive"]);
const VALID_PAYMENT_METHODS = new Set(["credit_card", "debit_card", "pix", "boleto"]);

export function positiveInt(value, field) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed <= 0 || String(value).trim() === "") {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [
      { field, message: "Must be a positive integer" }
    ]);
  }
  return parsed;
}

export function pagination(page, pageSize) {
  const parsedPage = positiveInt(page ?? "1", "page");
  const parsedPageSize = positiveInt(pageSize ?? "50", "pageSize");
  if (parsedPageSize > 100) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [
      { field: "pageSize", message: "Must be between 1 and 100" }
    ]);
  }
  return { page: parsedPage, pageSize: parsedPageSize };
}

function requireObject(payload) {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", [
      { field: "$", message: "Must be a JSON object" }
    ]);
  }
  return payload;
}

function requiredString(payload, key, details, field = key) {
  const value = payload[key];
  if (typeof value !== "string" || value.trim() === "") {
    details.push({ field, message: "Required non-empty string" });
    return "";
  }
  return value.trim();
}

function optionalString(payload, key) {
  const value = payload[key];
  if (value === null || value === undefined) {
    return null;
  }
  return String(value).trim();
}

function requiredBool(payload, key, details, field = key) {
  const value = payload[key];
  if (typeof value !== "boolean") {
    details.push({ field, message: "Required boolean" });
    return false;
  }
  return value;
}

function positiveIntField(value, field, details) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    details.push({ field, message: "Must be a positive integer" });
    return 0;
  }
  return parsed;
}

function address(payload, details) {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    details.push({ field: "address", message: "Required object" });
    return {};
  }
  return {
    label: requiredString(payload, "label", details, "address.label"),
    street: requiredString(payload, "street", details, "address.street"),
    number: requiredString(payload, "number", details, "address.number"),
    complement: optionalString(payload, "complement"),
    district: requiredString(payload, "district", details, "address.district"),
    city: requiredString(payload, "city", details, "address.city"),
    state: requiredString(payload, "state", details, "address.state"),
    postalCode: requiredString(payload, "postalCode", details, "address.postalCode"),
    isDefault: requiredBool(payload, "isDefault", details, "address.isDefault")
  };
}

export function createCustomer(payload) {
  payload = requireObject(payload);
  const details = [];
  const result = {
    fullName: requiredString(payload, "fullName", details),
    email: requiredString(payload, "email", details),
    documentNumber: requiredString(payload, "documentNumber", details),
    phone: optionalString(payload, "phone"),
    address: address(payload.address, details)
  };
  if (result.email && !result.email.includes("@")) {
    details.push({ field: "email", message: "Must be a valid email-like value" });
  }
  if (details.length > 0) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
  }
  return result;
}

export function updateCustomer(payload) {
  payload = requireObject(payload);
  const details = [];
  const fullName = requiredString(payload, "fullName", details);
  const status = requiredString(payload, "status", details);
  if (status && !VALID_STATUSES.has(status)) {
    details.push({ field: "status", message: "Must be active or inactive" });
  }
  const result = {
    fullName,
    phone: optionalString(payload, "phone"),
    status,
    address: address(payload.address, details)
  };
  if (details.length > 0) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
  }
  return result;
}

export function createOrder(payload) {
  payload = requireObject(payload);
  const details = [];
  const customerId = positiveIntField(payload.customerId, "customerId", details);
  const addressId = positiveIntField(payload.addressId, "addressId", details);
  const items = [];

  if (!Array.isArray(payload.items) || payload.items.length === 0) {
    details.push({ field: "items", message: "Must contain at least one item" });
  } else {
    payload.items.forEach((item, index) => {
      if (item === null || typeof item !== "object" || Array.isArray(item)) {
        details.push({ field: `items[${index}]`, message: "Must be an object" });
        return;
      }
      items.push({
        productId: positiveIntField(item.productId, `items[${index}].productId`, details),
        quantity: positiveIntField(item.quantity, `items[${index}].quantity`, details)
      });
    });
  }

  let method = "";
  if (payload.payment === null || typeof payload.payment !== "object" || Array.isArray(payload.payment)) {
    details.push({ field: "payment", message: "Required object" });
  } else {
    method = requiredString(payload.payment, "method", details);
    if (method && !VALID_PAYMENT_METHODS.has(method)) {
      details.push({ field: "payment.method", message: "Invalid payment method" });
    }
  }

  if (details.length > 0) {
    throw new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details);
  }

  return {
    customerId,
    addressId,
    items,
    payment: { method }
  };
}
