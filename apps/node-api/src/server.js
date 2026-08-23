import express from "express";

import { loadConfig } from "./config.js";
import { createPool } from "./db.js";
import { ApiError, errorMiddleware } from "./errors.js";
import * as repository from "./repository.js";
import * as validation from "./validation.js";

const config = loadConfig();
const pool = createPool(config);
const app = express();
const rawBodyBytes = Symbol("rawBodyBytes");
const jsonBody = [
  express.json({
    limit: "1mb",
    strict: false,
    type: "*/*",
    verify: (request, _response, buffer) => {
      request[rawBodyBytes] = buffer.length;
    }
  }),
  (request, _response, next) => {
    if (!validation.hasJsonPayload(request[rawBodyBytes])) {
      next(new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", [
        { field: "$", message: "Invalid JSON" }
      ]));
      return;
    }
    next();
  }
];

app.set("strict routing", true);

app.get("/health", (_request, response) => {
  response.json({ status: "ok" });
});

app.get("/customers", async (request, response, next) => {
  try {
    const { page, pageSize } = validation.pagination(request.query.page, request.query.pageSize);
    response.json(await repository.listCustomers(pool, page, pageSize));
  } catch (error) {
    next(error);
  }
});

app.post("/customers", ...jsonBody, async (request, response, next) => {
  try {
    const payload = validation.createCustomer(request.body);
    response.status(201).json(await repository.createCustomer(pool, payload));
  } catch (error) {
    next(error);
  }
});

app.get("/customers/:id", async (request, response, next) => {
  try {
    const customerId = validation.positiveInt(request.params.id, "id");
    response.json(await repository.getCustomer(pool, customerId));
  } catch (error) {
    next(error);
  }
});

app.put("/customers/:id", ...jsonBody, async (request, response, next) => {
  try {
    const customerId = validation.positiveInt(request.params.id, "id");
    const payload = validation.updateCustomer(request.body);
    response.json(await repository.updateCustomer(pool, customerId, payload));
  } catch (error) {
    next(error);
  }
});

app.get("/products", async (request, response, next) => {
  try {
    const categoryId = validation.positiveInt(request.query.categoryId, "categoryId");
    response.json(await repository.listProducts(pool, categoryId));
  } catch (error) {
    next(error);
  }
});

app.post("/orders", ...jsonBody, async (request, response, next) => {
  try {
    const payload = validation.createOrder(request.body);
    response.status(201).json(await repository.createOrder(pool, payload));
  } catch (error) {
    next(error);
  }
});

app.get("/orders/:id", async (request, response, next) => {
  try {
    const orderId = validation.positiveInt(request.params.id, "id");
    response.json(await repository.getOrder(pool, orderId));
  } catch (error) {
    next(error);
  }
});

app.use((error, _request, response, next) => {
  if (error instanceof SyntaxError && "body" in error) {
    next(new ApiError(400, "VALIDATION_ERROR", "Invalid request payload", [{ field: "$", message: "Invalid JSON" }]));
    return;
  }
  next(error);
});

app.all(["/health", "/customers", "/customers/:id", "/products", "/orders", "/orders/:id"], (_request, response) => {
  response.status(405).json({
    error: { code: "METHOD_NOT_ALLOWED", message: "Method not allowed", details: [] }
  });
});

app.use((_request, response) => {
  response.status(404).json({
    error: { code: "NOT_FOUND", message: "Route not found", details: [] }
  });
});

app.use(errorMiddleware);

const server = app.listen(config.port, "0.0.0.0", () => {
  console.log(`Node API listening on ${config.port}`);
});

async function shutdown() {
  server.close(async () => {
    await pool.end();
    process.exit(0);
  });
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
