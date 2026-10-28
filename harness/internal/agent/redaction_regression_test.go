package agent

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/url"
	"strings"
	"testing"
)

func TestUnknownTokenIsRedactedInFreeTextAndKeys(t *testing.T) {
	token := "sk-proj-arbitrarySecret123456789"
	input, _ := json.Marshal(map[string]any{token: "safe", "message": "text " + token, "checkpoint": map[string]any{"note": token}})
	clean := sanitizeJSON(input)
	if strings.Contains(string(clean), token) {
		t.Fatal("unrecognized credential leaked in a key or free text")
	}
}

func TestEncodedKnownTokensAndKeyCollisions(t *testing.T) {
	token := "credential.with+slash/123456"
	variants := []string{token, url.QueryEscape(token), base64.StdEncoding.EncodeToString([]byte(token)),
		base64.RawURLEncoding.EncodeToString([]byte(token)), hex.EncodeToString([]byte(token))}
	input := map[string]string{"[redacted]": "original marker"}
	for i, value := range variants {
		input[value] = "value-" + string(rune('a'+i))
	}
	data, _ := json.Marshal(input)
	clean := sanitizeJSONWithToken(data, token)
	var output map[string]string
	if err := json.Unmarshal(clean, &output); err != nil {
		t.Fatal(err)
	}
	if len(output) != len(input) {
		t.Fatal("cleaned keys collided and overwrote values", output)
	}
	for _, value := range variants {
		if strings.Contains(string(clean), value) {
			t.Fatal("encoded credential leaked")
		}
	}
	for _, value := range input {
		found := false
		for _, saved := range output {
			found = found || saved == value
		}
		if !found {
			t.Fatal("collision lost a value", value)
		}
	}
	if again := sanitizeJSONWithToken(clean, token); string(again) != string(clean) {
		t.Fatal("redaction is not deterministic/idempotent")
	}
}

func TestTruncatedReportRetainsExactNumbers(t *testing.T) {
	data, _ := json.Marshal(map[string]any{"lease_id": "lease", "event_id": "event", "exit_code": json.Number("9007199254740993"), "message": strings.Repeat("x", maxReportBytes+1)})
	clean := truncateReport(data)
	if !strings.Contains(string(clean), "9007199254740993") || len(clean) > maxReportBytes {
		t.Fatal("report truncation rounded integer")
	}
}

func TestMixedEncodedKnownTokenCannotLeak(t *testing.T) {
	token := "sensitive-authentication-value"
	for _, value := range []string{`%73ensitive-authentication-value`, `%2573ensitive-authentication-value`,
		`\u0073ensitive-authentication-value`, `&#115;ensitive-authentication-value`, `invalid% and %73ensitive-authentication-value`} {
		data, _ := json.Marshal(map[string]string{value: "kept", "message": "prefix " + value})
		var clean map[string]string
		if err := json.Unmarshal(sanitizeJSONWithToken(data, token), &clean); err != nil {
			t.Fatal(err)
		}
		for key, message := range clean {
			if strings.Contains(key, value) || strings.Contains(message, value) {
				t.Fatal("mixed encoding leaked")
			}
		}
	}
}

func TestBase64CredentialsAndStringValuesAreRedactedAsWholeFields(t *testing.T) {
	token := "known-secret-token-value"
	authorization := "Basic " + base64.StdEncoding.EncodeToString([]byte("x:"+token))
	blob := base64.StdEncoding.EncodeToString([]byte(`{"credential":"` + token + `"}`))
	data, _ := json.Marshal(map[string]string{"Authorization": authorization, "blob": blob})
	var clean map[string]string
	if err := json.Unmarshal(sanitizeJSONWithToken(data, token), &clean); err != nil {
		t.Fatal(err)
	}
	if clean["Authorization"] != redacted || clean["blob"] != redacted {
		t.Fatal("base64 secret did not mask its complete source field", clean)
	}
}
