package agent

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"agentsflow/harness/internal/leases"
)

func TestRunnerFailuresPreserveCheckpoint(t *testing.T) {
	for _, mode := range []string{"failure", "exit", "malformed", "no-terminal", "descendant"} {
		t.Run(mode, func(t *testing.T) {
			s := newFlowServer(t, "publish")
			e, _ := fixture(t, s, mode)
			cancel, done := start(t, e)
			await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
			cancel()
			<-done
			kinds := reportKinds(s)
			if kinds[len(kinds)-1] != "fail" {
				t.Fatal("runner failure did not produce fail", kinds)
			}
			s.mu.Lock()
			checkpoint := string(s.checkpoint)
			s.mu.Unlock()
			if (mode == "exit" || mode == "failure") && !strings.Contains(checkpoint, "saved-step") {
				t.Fatal("checkpoint lost")
			}
		})
	}
}

func TestReport409StopsWithoutFail(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining = "plan", 409, 1
	e, root := fixture(t, s, "normal")
	_, done := start(t, e)
	if err := <-done; !errors.Is(err, leases.ErrLeaseLost) {
		t.Fatal("409 must stop", err)
	}
	if got := reportKinds(s); len(got) != 0 {
		t.Fatal("reports after lost lease", got)
	}
	state := readJournal(t, root)
	if !state.Lost || state.Pending == nil {
		t.Fatal("lost lease journal not preserved")
	}
}

func TestHeartbeat409StopsWaiting(t *testing.T) {
	s := newFlowServer(t, "pending-plan")
	e, _ := fixture(t, s, "normal")
	_, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.planPolls > 1 })
	s.mu.Lock()
	s.loseHeartbeat = true
	s.mu.Unlock()
	if err := <-done; !errors.Is(err, leases.ErrLeaseLost) {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan"}) {
		t.Fatal(got)
	}
	s.mu.Lock()
	before := s.heartbeats
	s.mu.Unlock()
	time.Sleep(30 * time.Millisecond)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.heartbeats != before {
		t.Fatal("heartbeat leaked after shutdown")
	}
}

func TestDecisionTimeoutPreservesTask(t *testing.T) {
	s := newFlowServer(t, "pending-plan")
	e, root := fixture(t, s, "normal")
	e.options.DecisionTimeout = 30 * time.Millisecond
	_, done := start(t, e)
	if err := <-done; !errors.Is(err, ErrDecisionTimeout) {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan"}) {
		t.Fatal(got)
	}
	if state := readJournal(t, root); state.Claim == nil || state.Stage != "wait_plan" {
		t.Fatal("task was discarded")
	}
}

func TestRetryReportUsesSameIdentity(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining = "plan", 503, 4
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("duplicate report", got)
	}
}
