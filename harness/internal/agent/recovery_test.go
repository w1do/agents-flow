package agent

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
	"agentsflow/harness/internal/workspace"
)

func TestResumeAfterCancellation(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, root := fixture(t, s, "block")
	path := filepath.Join(filepath.Dir(root), "repository-task-task")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool {
		_, err := os.Stat(filepath.Join(path, "descendant.pid"))
		return strings.Contains(string(s.checkpoint), "saved-step") && err == nil
	})
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	assertDescendantStopped(t, path)
	state := readJournal(t, root)
	if state.Stage != "implementation" || !strings.Contains(string(state.Checkpoint), "saved-step") {
		t.Fatal("checkpoint not journaled")
	}
	testutil.Write(t, filepath.Join(path, "preserved.txt"), "preserve across restart")
	e.cfg.Runner.Command[len(e.cfg.Runner.Command)-1] = "resume"
	resumed, err := New(e.cfg, "agent-secret", e.options)
	if err != nil {
		t.Fatal(err)
	}
	cancel, done = start(t, resumed)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	if testutil.Read(t, filepath.Join(path, "preserved.txt")) != "preserve across restart" {
		t.Fatal("worktree replaced")
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("resume restarted plan", got)
	}
}

func TestReplayAcknowledgementLostAcrossRestart(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining, s.commitFault = "plan", 503, 100, true
	e, root := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.firstFaultKey != "" })
	cancel()
	<-done
	state := readJournal(t, root)
	if state.Pending == nil || state.Pending.Kind != "plan" {
		t.Fatal("ambiguous report not preserved")
	}
	s.mu.Lock()
	s.faultRemaining = 0
	key := s.firstFaultKey
	s.mu.Unlock()
	if state.Pending.Key != key {
		t.Fatal("durable key changed")
	}
	resumed, err := New(e.cfg, "agent-secret", e.options)
	if err != nil {
		t.Fatal(err)
	}
	cancel, done = start(t, resumed)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		s.mu.Lock()
		last := s.reports[len(s.reports)-1].body
		s.mu.Unlock()
		t.Fatal("duplicate report", got, string(last["message"]))
	}
}

func TestServerCheckpointAndExistingWorktree(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.status, s.planDecision = "active", "approved"
	s.checkpoint = []byte(`{"harness":{"stage":"implementation","plan_text":"Approved plan"},"runner":{"step":"saved-step"}}`)
	e, root := fixture(t, s, "resume")
	path, err := workspace.Ensure(context.Background(), root, "task")
	if err != nil {
		t.Fatal(err)
	}
	testutil.Write(t, filepath.Join(path, "preserved.txt"), "server checkpoint")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"result", "publication-result"}) {
		t.Fatal("server checkpoint not resumed", got)
	}
	if testutil.Read(t, filepath.Join(path, "preserved.txt")) != "server checkpoint" {
		t.Fatal("worktree lost")
	}
}

func TestLargeCheckpointSurvivesSnapshotServerAndRestore(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, root := fixture(t, s, "large-checkpoint")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool {
		return strings.Contains(string(s.checkpoint), strings.Repeat("x", 64))
	})
	cancel()
	<-done

	state := readJournal(t, root)
	if len(state.Checkpoint) < 300<<10 || strings.Contains(string(state.Checkpoint), `"truncated":true`) {
		t.Fatal("large checkpoint was truncated in local snapshot")
	}
	var serverCheckpoint checkpoint
	if err := json.Unmarshal(s.checkpoint, &serverCheckpoint); err != nil || len(serverCheckpoint.Runner) < 300<<10 {
		t.Fatal("large checkpoint was truncated in server report", err)
	}
	restored := &Engine{}
	restored.restoreCheckpoint(s.checkpoint)
	if len(restored.state.Checkpoint) < 300<<10 || strings.Contains(string(restored.state.Checkpoint), `"truncated":true`) {
		t.Fatal("restored checkpoint is truncated")
	}
}
