package leases

import (
	"context"
	"errors"
	"sync"

	"agentsflow/harness/internal/api"
)

var (
	ErrBusy      = errors.New("agent is busy")
	ErrLeaseLost = errors.New("lease lost; stop work on the task")
)

type Server interface {
	Claim(context.Context, string, string) (*api.ClaimResponse, error)
	Heartbeat(context.Context, string, api.HeartbeatRequest) (api.HeartbeatResponse, error)
}

type State struct {
	TaskID, LeaseID string
	Lost            bool
}

type Manager struct {
	mu                   sync.Mutex
	server               Server
	agentID              string
	state                State
	claiming, remoteBusy bool
	claimKey             string
}

func New(server Server, agentID string) *Manager {
	return &Manager{server: server, agentID: agentID}
}

func (m *Manager) State() State {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state
}

// Claim attempts immediately. The future run loop waits its poll interval only
// after an empty result; network calls never hold the state mutex.
func (m *Manager) Claim(ctx context.Context) (*api.ClaimResponse, error) {
	m.mu.Lock()
	if m.state.TaskID != "" || m.claiming || m.remoteBusy {
		m.mu.Unlock()
		return nil, ErrBusy
	}
	m.claiming = true
	if m.claimKey == "" {
		m.claimKey = api.NewKey()
	}
	key := m.claimKey
	m.mu.Unlock()
	result, err := m.server.Claim(ctx, m.agentID, key)
	m.mu.Lock()
	defer m.mu.Unlock()
	m.claiming = false
	// Keep the key after an ambiguous network failure for safe recovery.
	var apiErr *api.Error
	if err == nil || errors.As(err, &apiErr) && apiErr.StatusCode < 500 {
		m.claimKey = ""
	}
	if errors.As(err, &apiErr) && apiErr.StatusCode == 409 {
		m.remoteBusy = true
		return nil, ErrBusy
	}
	if err != nil || result == nil {
		return nil, err
	}
	m.state = State{TaskID: result.Task.ID, LeaseID: result.LeaseID}
	return result, nil
}

// Release is explicit: connection failures and TTL expiry never finish a task.
func (m *Manager) Release() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.state = State{}
	m.remoteBusy = false
}
