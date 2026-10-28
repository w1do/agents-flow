package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestArbitraryResponseNumbersStayExact(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"id":9007199254740993}`))
	}))
	defer server.Close()
	client, err := New(server.URL, "token", Options{})
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	if _, err := client.Request(context.Background(), "GET", "/state", "", nil, &value); err != nil {
		t.Fatal(err)
	}
	if value["id"] != json.Number("9007199254740993") {
		t.Fatal("API rounded number", value)
	}
}
