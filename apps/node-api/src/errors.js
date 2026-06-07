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

export function errorMiddleware(error, _request, response, _next) {
  if (error instanceof ApiError) {
    response.status(error.statusCode).json(errorBody(error.code, error.message, error.details));
    return;
  }

  response.status(500).json(
    errorBody("INTERNAL_ERROR", "Internal server error", [{ message: error.message }])
  );
}
