package agent

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentsflow/harness/internal/config"
)

func TestConfigChangeIsNotRetryable(t *testing.T) {
	err := fmt.Errorf("wrapped: %w", &config.ChangedError{})
	if retryable(err) {
		t.Fatal("config changes must not be retried")
	}
}

func TestConfigChangeWhileWaitingForTaskStopsHarness(t *testing.T) {
	s := newFlowServer(t, "publish")
	// Keep the queue empty so the engine stays in waitClaim.
	s.claimed, s.completed = true, true
	original, root := fixture(t, s, "normal")
	cfg, token, err := config.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	e, err := New(cfg, token, original.options)
	if err != nil {
		t.Fatal(err)
	}
	cancel, done := start(t, e)
	defer cancel()
	await(t, s, func(s *flowServer) bool { return s.claims > 0 })
	path := filepath.Join(root, "workflow/config.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(data, []byte("\n# edited while idle\n")...), 0600); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		var changed *config.ChangedError
		if !errors.As(err, &changed) || err.Error() != "config changed, restart harness" {
			t.Fatal("expected permanent config change error", err)
		}
	case <-time.After(time.Second):
		t.Fatal("harness kept retrying after config changed")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.reports) != 0 || s.taskHeartbeats != 0 {
		t.Fatal("task activity occurred while queue was empty")
	}
}
