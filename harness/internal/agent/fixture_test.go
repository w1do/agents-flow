package agent

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/skills"
	"agentsflow/harness/internal/testutil"
)

func fixture(t *testing.T, server *flowServer, mode string) (*Engine, string) {
	t.Helper()
	t.Setenv("GORACE", "atexit_sleep_ms=0")
	t.Setenv("AGENTS_FLOW_INIT_TOKEN", "init-secret")
	t.Setenv("AGENTS_FLOW_AGENT_TOKEN", "agent-secret")
	root := testutil.Repository(t)
	dir := filepath.Join(root, "workflow")
	if err := os.Mkdir(dir, 0755); err != nil {
		t.Fatal(err)
	}
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cfg := config.Config{ServerURL: server.server.URL, ProjectID: "project", AgentID: "agent", WorkspacePath: root,
		GitRemote: "origin", PollIntervalSeconds: 5, LeaseTTLSeconds: 60,
		Runner: config.Runner{Environment: map[string]string{"GORACE": "atexit_sleep_ms=0"}, Command: []string{exe, "-test.run=^TestRunnerHelper$", "--", mode}}}
	if err := config.Write(dir, cfg, "agent-secret"); err != nil {
		t.Fatal(err)
	}
	if err := skills.Apply(filepath.Join(dir, "skills"), assignedSkills()); err != nil {
		t.Fatal(err)
	}
	engine, err := New(cfg, "agent-secret", Options{PollInterval: 5 * time.Millisecond, HeartbeatInterval: 10 * time.Millisecond,
		RetryBackoff: time.Millisecond, DecisionTimeout: 5 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	return engine, root
}

func start(t *testing.T, engine *Engine) (context.CancelFunc, <-chan error) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- engine.Run(ctx); close(done) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("run did not stop")
		}
	})
	return cancel, done
}

func await(t *testing.T, s *flowServer, condition func(*flowServer) bool) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		ready := condition(s)
		s.mu.Unlock()
		if ready {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("timed out waiting for server state")
}

func reportKinds(s *flowServer) []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	var kinds []string
	for _, report := range s.reports {
		if report.kind != "events" {
			kinds = append(kinds, report.kind)
		}
	}
	return kinds
}

func readJournal(t *testing.T, root string) durableState {
	t.Helper()
	store := &journal{dir: filepath.Join(root, ".git", "agents-flow-harness")}
	state, err := store.load()
	if err != nil {
		t.Fatal(err)
	}
	return state
}
