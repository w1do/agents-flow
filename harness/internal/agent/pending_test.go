package agent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/api"
)

func TestInvalidLegacyPendingIsNotGivenANewKey(t *testing.T) {
	for _, key := range []string{"", "different-key"} {
		state := durableState{Claim: &api.ClaimResponse{LeaseID: "lease"}, Pending: &pendingReport{
			Kind: "fail", Next: "done", Key: key, Body: json.RawMessage(`{"lease_id":"lease","event_id":"original-key","message":"failed"}`)}}
		store := &journal{dir: t.TempDir()}
		data, _ := json.Marshal(state)
		if err := os.WriteFile(filepath.Join(store.dir, "state.json"), data, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := store.load(); err == nil {
			t.Fatal("unsafe pending would be retried under a different identity")
		}
	}
}
