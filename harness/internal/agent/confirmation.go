package agent

import (
	"errors"
	"sync"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/leases"
)

// A finished heartbeat is not evidence that our final write failed: its commit
// can precede its HTTP response. Only this immutable pending key may be replayed
// while confirmation is unresolved; an actual report conflict still stops work.
type confirmationGate struct {
	mu  sync.Mutex
	key string
}

func (g *confirmationGate) arm(pending *pendingReport) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.key = ""
	if pending != nil && pending.Next == "done" && (pending.Kind == "fail" || pending.Kind == "publication-result") {
		g.key = pending.Key
	}
}

func (g *confirmationGate) confirming(err error) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	var serverErr *api.Error
	return g.key != "" && errors.Is(err, leases.ErrLeaseLost) && errors.As(err, &serverErr) && serverErr.TaskFinished
}
