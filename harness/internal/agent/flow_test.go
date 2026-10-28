package agent

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"reflect"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestEndToEndPublish(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, root := fixture(t, s, "normal")
	before := testutil.Git(t, root, "status", "--porcelain", "--untracked-files=all")
	head := testutil.Git(t, root, "rev-parse", "HEAD")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal("shutdown", err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("stages", got)
	}
	if testutil.Git(t, root, "status", "--porcelain", "--untracked-files=all") != before ||
		testutil.Git(t, root, "rev-parse", "HEAD") != head || testutil.Git(t, root, "branch", "--show-current") != "main" {
		t.Fatal("primary working copy changed")
	}
	path := filepath.Join(filepath.Dir(root), "repository-task-task")
	if testutil.Read(t, filepath.Join(path, "change.txt")) != "task progress" {
		t.Fatal("runner did not use task worktree")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.heartbeats == 0 {
		t.Fatal("heartbeat missing")
	}
	for _, report := range s.reports {
		if report.kind == "result" {
			var data struct {
				Tests          []json.RawMessage `json:"tests"`
				Implementation string            `json:"implementation"`
			}
			if json.Unmarshal(report.body["result_data"], &data) != nil || len(data.Tests) != 1 || data.Implementation != "kept" {
				t.Fatal("test results missing")
			}
		}
	}
}

func TestRework(t *testing.T) {
	s := newFlowServer(t, "rework")
	e, root := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "result", "publication-result"}) {
		t.Fatal("rework did not rerun implementation and testing", got)
	}
	if testutil.Read(t, filepath.Join(filepath.Dir(root), "repository-task-task", "feedback.txt")) != "Please revise" {
		t.Fatal("rework feedback missing")
	}
}

func TestRejectedPlanReturnsToPlanningAndTrashStops(t *testing.T) {
	t.Run("rejected", func(t *testing.T) {
		s := newFlowServer(t, "rejected")
		e, _ := fixture(t, s, "normal")
		cancel, done := start(t, e)
		await(t, s, func(s *flowServer) bool {
			count := 0
			for _, report := range s.reports {
				if report.kind == "plan" {
					count++
				}
			}
			return count >= 2
		})
		cancel()
		if err := <-done; !errors.Is(err, context.Canceled) {
			t.Fatal("shutdown", err)
		}
		got := reportKinds(s)
		if len(got) < 2 || got[0] != "plan" || got[1] != "plan" {
			t.Fatal("rejected plan did not return to planning", got)
		}
	})
	t.Run("trash", func(t *testing.T) {
		s := newFlowServer(t, "trash")
		e, _ := fixture(t, s, "normal")
		_, done := start(t, e)
		if err := <-done; err != nil {
			t.Fatal(err)
		}
		if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan"}) {
			t.Fatal(got)
		}
	})
}

func TestKeepReadyMaintainsLeaseWithoutPublication(t *testing.T) {
	s := newFlowServer(t, "keep_ready")
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.resultPolls > 3 && s.heartbeats > 2 })
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result"}) {
		t.Fatal("unexpected publication", got)
	}
}
