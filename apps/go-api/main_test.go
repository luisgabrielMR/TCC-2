package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func decodedObject(t *testing.T, value string) map[string]any {
	t.Helper()
	decoder := json.NewDecoder(strings.NewReader(value))
	decoder.UseNumber()
	var result map[string]any
	if err := decoder.Decode(&result); err != nil {
		t.Fatal(err)
	}
	return result
}

func TestCreateCustomerNormalizesASCIIState(t *testing.T) {
	raw := decodedObject(t, `{
		"fullName":" Test Customer ","email":"test@example.com","documentNumber":"DOC-1",
		"address":{"label":"Home","street":"Main","number":"10","district":"Center",
		"city":"Sao Paulo","state":" sp ","postalCode":"01001000","isDefault":true}}
	`)
	result, err := validateCreateCustomer(raw)
	if err != nil {
		t.Fatal(err)
	}
	if result.FullName != "Test Customer" || result.Address == nil || result.Address.State != "SP" {
		t.Fatalf("unexpected normalized customer: %#v", result)
	}
}

func TestCreateOrderUsesCanonicalPaymentField(t *testing.T) {
	raw := decodedObject(t, `{"customerId":1,"addressId":1,"items":[{"productId":1,"quantity":1}],"payment":{}}`)
	_, err := validateCreateOrder(raw)
	api, ok := err.(apiError)
	if !ok || len(api.Details) != 1 || api.Details[0]["field"] != "payment.method" {
		t.Fatalf("unexpected error: %#v", err)
	}
}

func TestPositiveIntRejectsNonCanonicalText(t *testing.T) {
	if value, err := positiveInt("2147483647", "id"); err != nil || value != 2147483647 {
		t.Fatalf("valid int32 rejected: value=%d err=%v", value, err)
	}
	for _, value := range []string{"1.0", "+1", " 1 ", "2147483648", "１"} {
		if _, err := positiveInt(value, "id"); err == nil {
			t.Fatalf("invalid value accepted: %q", value)
		}
	}
}

func TestRecoverInternalErrorsUsesCanonicalJSON(t *testing.T) {
	handler := recoverInternalErrors(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("test panic")
	}))
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/health", nil))

	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("unexpected status: %d", recorder.Code)
	}
	expected := `{"error":{"code":"INTERNAL_ERROR","details":[],"message":"Internal server error"}}`
	if recorder.Body.String() != expected {
		t.Fatalf("unexpected body: %s", recorder.Body.String())
	}
}
