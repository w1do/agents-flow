package agent

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func TestSanitizePreservesLargeCheckpointWithoutMutatingState(t *testing.T) {
	checkpoint := make(map[string]string, 1001)
	for i := 0; i < 1001; i++ {
		checkpoint[fmt.Sprintf("field-%04d", i)] = "safe"
	}
	input := map[string]any{"checkpoint": checkpoint}
	before, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	clean := sanitizeJSON(data)
	var output map[string]map[string]string
	if err := json.Unmarshal(clean, &output); err != nil {
		t.Fatal(err)
	}
	if got := len(output["checkpoint"]); got != 1001 {
		t.Fatalf("checkpoint fields lost: got %d, want 1001", got)
	}
	after, err := json.Marshal(input)
	if err != nil || string(after) != string(before) {
		t.Fatal("sanitizing checkpoint mutated current state", err)
	}
}

func TestBase64AuthorizationPrefixAndBlockBoundary(t *testing.T) {
	token := "known-secret-token-value"
	encoded := base64.StdEncoding.EncodeToString([]byte("x:" + token))
	for _, wrapped := range []string{"b64=" + encoded, "base64:" + encoded,
		"base64," + encoded, "data:text/plain;base64," + encoded} {
		got := sanitizeJSONWithToken(marshalAuthorization(t, wrapped), token)
		var output map[string]string
		if err := json.Unmarshal(got, &output); err != nil || output["message"] != redacted {
			t.Fatal("base64-prefixed authorization was not redacted", err)
		}
	}

	plain := strings.Repeat("a", 49146) + "x:" + token + strings.Repeat("b", 64)
	encoded = base64.StdEncoding.EncodeToString([]byte(plain))
	if got := sanitizeJSONWithToken(marshalAuthorization(t, encoded), token); !strings.Contains(string(got), redacted) {
		t.Fatal("base64 secret crossing a 64 KiB block boundary was not redacted")
	}
}

func TestOrdinaryTextWithoutSecretsIsUnchanged(t *testing.T) {
	const message = "ordinary readable text without credentials"
	data := marshalAuthorization(t, message)
	clean := sanitizeJSONWithToken(data, "known-secret-token-value")
	var output map[string]string
	if err := json.Unmarshal(clean, &output); err != nil {
		t.Fatal(err)
	}
	if output["message"] != message {
		t.Fatalf("ordinary text changed: %q", output["message"])
	}
}

func marshalAuthorization(t *testing.T, value string) []byte {
	t.Helper()
	data, err := json.Marshal(map[string]string{"message": value})
	if err != nil {
		t.Fatal(err)
	}
	return data
}
