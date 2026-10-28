package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"agentsflow/harness/internal/api"
)

func delayedCompletionServer(t *testing.T, s *flowServer) (func(), *atomic.Int32) {
	t.Helper()
	s.server.Close()
	hold := make(chan struct{})
	var once sync.Once
	release := func() { once.Do(func() { close(hold) }) }
	var delayed atomic.Bool
	finished := &atomic.Int32{}
	s.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/heartbeat") {
			data, _ := io.ReadAll(r.Body)
			r.Body = io.NopCloser(bytes.NewReader(data))
			var body api.HeartbeatRequest
			_ = json.Unmarshal(data, &body)
			s.mu.Lock()
			completed := s.completed
			s.mu.Unlock()
			if completed && body.TaskID != nil {
				finished.Add(1)
				w.WriteHeader(409)
				_, _ = w.Write([]byte(`{"detail":"Task is finished"}`))
				return
			}
		}
		if strings.HasSuffix(r.URL.Path, "/publication-result") && delayed.CompareAndSwap(false, true) {
			recorder := httptest.NewRecorder()
			s.serve(recorder, r)
			<-hold
			w.WriteHeader(recorder.Code)
			_, _ = w.Write(recorder.Body.Bytes())
			return
		}
		s.serve(w, r)
	}))
	t.Cleanup(s.server.Close)
	t.Cleanup(release)
	return release, finished
}

func TestFinishedHeartbeatDoesNotLoseAcceptedFinalReport(t *testing.T) {
	s := newFlowServer(t, "publish")
	release, finished := delayedCompletionServer(t, s)
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(*flowServer) bool { return finished.Load() > 0 })
	select {
	case err := <-done:
		t.Fatalf("accepted final report was lost before confirmation: %v", err)
	default:
	}
	release()
	await(t, s, func(s *flowServer) bool { return s.claims > 1 })
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("duplicated final report", got)
	}
}

func TestAcceptedFinalPendingRecoversAfterRestart(t *testing.T) {
	s := newFlowServer(t, "publish")
	release, finished := delayedCompletionServer(t, s)
	e, root := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(*flowServer) bool { return finished.Load() > 0 })
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatal("accepted pending marked as lost", err)
	}
	state := readJournal(t, root)
	if state.Lost || state.Pending == nil || state.Pending.Next != "done" {
		t.Fatal("confirmation pending not preserved")
	}
	release()
	resumed, err := New(e.cfg, "agent-secret", e.options)
	if err != nil {
		t.Fatal(err)
	}
	cancel, done = start(t, resumed)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		ready := s.claims > 1
		s.mu.Unlock()
		if ready {
			break
		}
		select {
		case err := <-done:
			t.Fatal("pending replay stopped", err)
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	<-done
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "result", "publication-result"}) {
		t.Fatal("recovery duplicated reports", got)
	}
}
