package agent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/api"
)

func TestJournalPreservesFullClaimWithoutMutatingInput(t *testing.T) {
	store := &journal{dir: t.TempDir()}
	state := durableState{Stage: "planning", Claim: &api.ClaimResponse{LeaseID: "lease", Task: api.Task{ID: "task",
		SourceText: strings.Repeat("source ", maxReportBytes/4)}, Skills: []api.Skill{{Filename: "development--large.md", Content: strings.Repeat("skill ", 200000)}}}}
	before, _ := json.Marshal(state)
	if err := store.save(state); err != nil {
		t.Fatal(err)
	}
	after, _ := json.Marshal(state)
	if string(before) != string(after) {
		t.Fatal("saving the journal mutated the working task/skills")
	}
	info, err := os.Stat(filepath.Join(store.dir, "state.json"))
	if err != nil || info.Size() > maxReportBytes {
		t.Fatal("journal is not compact", err)
	}
	loaded, err := store.load()
	restored, _ := json.Marshal(loaded.Claim)
	want, _ := json.Marshal(state.Claim)
	if err != nil || string(restored) != string(want) {
		t.Fatal("full claim was not restored", err)
	}
}

func TestNumbersSurviveJournalAndCheckpointRestore(t *testing.T) {
	store := &journal{dir: t.TempDir()}
	state := durableState{ResultData: map[string]any{"id": json.Number("9007199254740993")}}
	if err := store.save(state); err != nil {
		t.Fatal(err)
	}
	loaded, err := store.load()
	if err != nil || loaded.ResultData["id"] != json.Number("9007199254740993") {
		t.Fatal("journal rounded integer", err, loaded.ResultData)
	}
	e := &Engine{}
	e.restoreCheckpoint([]byte(`{"harness":{"stage":"testing","result_data":{"id":9007199254740993}},"runner":{}}`))
	if e.state.ResultData["id"] != json.Number("9007199254740993") {
		t.Fatal("checkpoint rounded integer", e.state.ResultData)
	}
}
