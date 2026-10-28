package agent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/api"
)

func TestSnapshotsArePrivateSanitizedAndGarbageCollected(t *testing.T) {
	store := &journal{dir: t.TempDir()}
	token := "sk-proj-snapshotSecret123456789"
	state := durableState{Claim: &api.ClaimResponse{Task: api.Task{ID: "task", SourceText: "Input " + token}},
		ResultData: map[string]any{token: token}, Checkpoint: json.RawMessage(`{"step":1}`)}
	for i := range 5 {
		state.Checkpoint = json.RawMessage(`{"step":` + string(rune('0'+i)) + `}`)
		if err := store.save(state, token); err != nil {
			t.Fatal(err)
		}
	}
	entries, err := os.ReadDir(filepath.Join(store.dir, "snapshots"))
	if err != nil || len(entries) != 2 {
		t.Fatal("unreferenced snapshots accumulated", err, len(entries))
	}
	for _, entry := range entries {
		path := filepath.Join(store.dir, "snapshots", entry.Name())
		data, err := os.ReadFile(path)
		info, statErr := os.Stat(path)
		if err != nil || statErr != nil || info.Mode().Perm() != 0600 || strings.Contains(string(data), token) {
			t.Fatal("snapshot leaked a credential or permissions", err, statErr)
		}
	}
	if !strings.Contains(state.Claim.Task.SourceText, token) {
		t.Fatal("persistence changed the active input")
	}
}

func TestCorruptSnapshotCannotBeResumed(t *testing.T) {
	store := &journal{dir: t.TempDir()}
	if err := store.save(durableState{Stage: "planning"}); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(store.dir, "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	var compact durableState
	if err := json.Unmarshal(data, &compact); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(store.dir, "snapshots", compact.RuntimeSnapshot+".json"), []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.load(); err == nil {
		t.Fatal("corrupt snapshot was silently accepted")
	}
}
