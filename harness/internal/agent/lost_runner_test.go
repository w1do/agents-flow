package agent

import (
	"errors"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentsflow/harness/internal/leases"
)

func TestLeaseLossKillsActiveRunner(t *testing.T) {
	for _, source := range []string{"heartbeat", "report"} {
		t.Run(source, func(t *testing.T) {
			s := newFlowServer(t, "publish")
			if source == "report" {
				s.faultPath, s.faultCode, s.faultRemaining, s.faultNeedle = "events", 409, 1, "saved-step"
			}
			e, root := fixture(t, s, "block")
			_, done := start(t, e)
			if source == "heartbeat" {
				await(t, s, func(s *flowServer) bool { return strings.Contains(string(s.checkpoint), "saved-step") })
				s.mu.Lock()
				s.loseHeartbeat = true
				s.mu.Unlock()
			}
			if err := <-done; !errors.Is(err, leases.ErrLeaseLost) {
				t.Fatal("lost lease did not stop runner", err)
			}
			assertDescendantStopped(t, filepath.Join(filepath.Dir(root), "repository-task-task"))
			if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan"}) {
				t.Fatal("reports after lease loss", got)
			}
			state := readJournal(t, root)
			if !state.Lost || !strings.Contains(string(state.Checkpoint), "saved-step") {
				t.Fatal("checkpoint lost")
			}
		})
	}
}
