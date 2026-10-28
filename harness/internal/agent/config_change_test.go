package agent

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentsflow/harness/internal/config"
)

func TestRunRejectsChangedLoadedConfigBeforeClaim(t *testing.T) {
	s := newFlowServer(t, "publish")
	original, root := fixture(t, s, "normal")
	cfg, token, err := config.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	e, err := New(cfg, token, original.options)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "workflow/config.yaml")
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString("\n# edited during run\n"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := e.Run(ctx); err == nil || err.Error() != "config changed, restart harness" {
		t.Fatal("expected config change error", err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.claims != 0 {
		t.Fatal("claimed with stale config")
	}
}

func TestTestingFactsSurviveIntoPublicationInput(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, _ := fixture(t, s, "facts")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, report := range s.reports {
		if report.kind == "publication-result" {
			var success bool
			if err := json.Unmarshal(report.body["success"], &success); err != nil || !success {
				t.Fatal("publication did not receive testing facts", err)
			}
			return
		}
	}
	t.Fatal("publication result missing")
}
