import assert from "node:assert/strict";
import test from "node:test";

import { createCustomer, createOrder, hasJsonPayload, positiveInt } from "../src/validation.js";


const address = {
  label: " Home ",
  street: " Main Street ",
  number: " 10 ",
  complement: null,
  district: " Center ",
  city: " Sao Paulo ",
  state: " sp ",
  postalCode: " 01001000 ",
  isDefault: true
};


test("customer validation trims strings and normalizes the state", () => {
  const result = createCustomer({
    fullName: " Test Customer ",
    email: " test@example.com ",
    documentNumber: " DOC-1 ",
    phone: null,
    address
  });
  assert.equal(result.fullName, "Test Customer");
  assert.equal(result.address.state, "SP");
  assert.equal(result.address.street, "Main Street");
});


test("order validation reports the canonical nested payment field", () => {
  assert.throws(
    () => createOrder({ customerId: 1, addressId: 1, items: [{ productId: 1, quantity: 1 }], payment: {} }),
    (error) => {
      assert.deepEqual(error.details, [{ field: "payment.method", message: "Required non-empty string" }]);
      return true;
    }
  );
});


test("path integers accept only positive ASCII integer text in int32 range", () => {
  assert.equal(positiveInt("2147483647", "id"), 2147483647);
  for (const value of ["1.0", "+1", " 1 ", "2147483648", "１"]) {
    assert.throws(() => positiveInt(value, "id"));
  }
});


test("empty HTTP body is not treated as an empty JSON object", () => {
  assert.equal(hasJsonPayload(undefined), false);
  assert.equal(hasJsonPayload(0), false);
  assert.equal(hasJsonPayload(2), true);
});
