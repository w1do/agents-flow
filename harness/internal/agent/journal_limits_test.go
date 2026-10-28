package agent

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/api"
)

func TestJournalStoresOversizedClaimSeparately(t *testing.T) {
	dir := t.TempDir()
	store := &journal{dir: dir}
	state := durableState{AgentID: "agent", ServerURL: "http://localhost", Stage: "planning",
		Claim: &api.ClaimResponse{LeaseID: "lease", Task: api.Task{ID: "task"}, Skills: []api.Skill{{Filename: "development--one.md", Content: strings.Repeat("large", maxReportBytes)}}}}
	if err := store.save(state); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(filepath.Join(dir, "state.json"))
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() > maxReportBytes {
		t.Fatalf("journal size %d exceeds limit", info.Size())
	}
	if state.Claim.Skills[0].Content != strings.Repeat("large", maxReportBytes) {
		t.Fatal("saving changed the active skill")
	}
	loaded, err := store.load()
	if err != nil || loaded.Claim.Skills[0].Content != state.Claim.Skills[0].Content || loaded.Claim.Skills[0].SnapshotContentMissing {
		t.Fatal("full skill snapshot was not restored", err)
	}
}
