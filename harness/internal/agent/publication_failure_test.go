package agent

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"reflect"
	"testing"
	"time"

	"agentsflow/harness/internal/leases"
)

func TestPublicationFailureUsesPublicationResult(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, _ := fixture(t, s, "publication-failure")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	if err := <-done; err != nil && err != context.Canceled {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("publication error used wrong report", got)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var success bool
	if json.Unmarshal(s.reports[len(s.reports)-1].body["success"], &success) != nil || success {
		t.Fatal("publication failure was not reported as unsuccessful")
	}
}

func TestPublicationMissingSnapshotUsesUnsuccessfulResult(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.missingPublicationSnapshot = true
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed })
	cancel()
	if err := <-done; err != nil && err != context.Canceled {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("missing publication snapshot used wrong report", got)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var success bool
	if json.Unmarshal(s.reports[len(s.reports)-1].body["success"], &success) != nil || success {
		t.Fatal("missing snapshot was not reported as unsuccessful")
	}
}

func TestFinalReportLeaseConflictStopsRun(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining = "publication-result", http.StatusConflict, 1
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	defer cancel()
	select {
	case err := <-done:
		if !errors.Is(err, leases.ErrLeaseLost) {
			t.Fatalf("run error = %v, want lease lost", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("run did not stop on lease conflict")
	}
	if s.completed {
		t.Fatal("lease conflict was treated as successful report")
	}
}

func TestFinalReportRetriesKeepHeartbeatUntilAccepted(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining = "publication-result", http.StatusServiceUnavailable, 4
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.firstFaultKey != "" && s.heartbeats >= 2 })
	s.mu.Lock()
	before := s.taskHeartbeats
	s.faultRemaining = 0
	s.mu.Unlock()
	await(t, s, func(s *flowServer) bool { return s.completed })
	s.mu.Lock()
	afterAcceptance := s.taskHeartbeats
	s.mu.Unlock()
	time.Sleep(30 * time.Millisecond)
	s.mu.Lock()
	after := s.taskHeartbeats
	s.mu.Unlock()
	if before < 2 {
		t.Fatal("heartbeats did not continue during report retries")
	}
	if after != afterAcceptance {
		t.Fatal("heartbeat continued after final report acceptance")
	}
	cancel()
	<-done
}

func TestHeartbeatLeaseLossStopsFinalReportRetries(t *testing.T) {
	s := newFlowServer(t, "publish")
	s.faultPath, s.faultCode, s.faultRemaining = "publication-result", http.StatusServiceUnavailable, 100
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.firstFaultKey != "" })
	s.mu.Lock()
	s.loseHeartbeat = true
	s.mu.Unlock()
	select {
	case err := <-done:
		if !errors.Is(err, leases.ErrLeaseLost) {
			t.Fatalf("run error = %v, want lost lease", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("lost lease did not stop final report retries")
	}
	cancel()
}
