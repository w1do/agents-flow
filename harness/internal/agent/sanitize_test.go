package agent

import (
	"strings"
	"testing"
)

func TestSanitizeReportSecrets(t *testing.T) {
	input := []byte(`{"agent_token":"actual","authorization":"arbitrary auth","access_token":"x","private_key":"y","password":"z","client_secret":"w","apiKey":"a","api_key":"b","refresh-token":"r","message":"Basic abc Token def token=actual and actual"}`)
	clean := string(sanitizeJSON(input))
	for _, secret := range []string{"actual", "\"abc\"", "\"def\"", "\"arbitrary auth\"", "\"x\"", "\"y\"", "\"z\"", "\"w\"", "\"a\"", "\"b\"", "\"r\""} {
		if strings.Contains(clean, secret) {
			t.Fatalf("secret remained in %s", clean)
		}
	}
	if !strings.Contains(clean, "[redacted]") {
		t.Fatal("redaction marker missing")
	}
}

func TestSanitizePreservesLargeInteger(t *testing.T) {
	input := []byte(`{"count":9007199254740993}`)
	if got := string(sanitizeJSON(input)); got != string(input) {
		t.Fatalf("round trip changed number: %s", got)
	}
}

func TestSanitizeMasksKnownAgentTokenAnywhere(t *testing.T) {
	clean := string(sanitizeJSONWithToken([]byte(`{"message":"prefix secret-suffix"}`), "secret"))
	if strings.Contains(clean, "secret") {
		t.Fatalf("known token remained in %s", clean)
	}
}
