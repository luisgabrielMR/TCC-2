export class ApiError extends Error {
  constructor(statusCode, code, message, details = []) {
    super(message);
    this.statusCode = statusCode;
    this.code = code;
    this.details = details;
  }
}

export function errorBody(code, message, details = []) {
  return {
    error: {
      code,
      message,
      details
    }
  };
}

const CONNECTION_ERROR_CODES = new Set([
  "ECONNREFUSED",
  "ECONNRESET",
  "EPIPE",
  "ETIMEDOUT",
  "ENETUNREACH",
  "EHOSTUNREACH",
  "ENOTFOUND",
  "EAI_AGAIN"
]);

export function isPgDriverError(error) {
  if (!error || typeof error !== "object") {
    return false;
  }
  if (Array.isArray(error.errors) && error.errors.some(isPgDriverError)) {
    return true;
  }
  if (error.cause && isPgDriverError(error.cause)) {
    return true;
  }
  if (error.name === "DatabaseError" || CONNECTION_ERROR_CODES.has(error.code)) {
    return true;
  }
  if (typeof error.code === "string" && /^[0-9A-Z]{5}$/.test(error.code)) {
    return true;
  }
  if (typeof error.message === "string" && /^(Connection terminated|connect ECONNREFUSED|timeout expired)/.test(error.message)) {
    return true;
  }
  return ["severity", "routine", "schema", "table", "constraint"].some((key) => key in error);
}

export function errorMiddleware(error, _request, response, _next) {
  if (error instanceof ApiError) {
    response.status(error.statusCode).json(errorBody(error.code, error.message, error.details));
    return;
  }

  if (isPgDriverError(error)) {
    response.status(500).json(errorBody("DATABASE_ERROR", "Database error"));
    return;
  }

  response.status(500).json(errorBody("INTERNAL_ERROR", "Internal server error"));
}
