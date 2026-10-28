package leases

import (
	"context"
	"errors"
	"fmt"
	"time"

	"agentsflow/harness/internal/api"
)

func (m *Manager) Heartbeat(ctx context.Context) error {
	state := m.State()
	if state.Lost {
		return ErrLeaseLost
	}
	input := api.HeartbeatRequest{}
	if state.TaskID != "" {
		input.TaskID, input.LeaseID = &state.TaskID, &state.LeaseID
	}
	result, err := m.server.Heartbeat(ctx, m.agentID, input)
	m.mu.Lock()
	defer m.mu.Unlock()
	// An in-flight response must not affect a later lease.
	if m.state.TaskID != state.TaskID || m.state.LeaseID != state.LeaseID {
		return err
	}
	var apiErr *api.Error
	if errors.As(err, &apiErr) && apiErr.StatusCode == 409 && state.TaskID != "" {
		m.state.Lost = true
		return fmt.Errorf("%w: %w", ErrLeaseLost, apiErr)
	}
	if err == nil {
		m.remoteBusy = result.Status == "busy"
	}
	return err
}

// StartHeartbeat returns immediately. Errors are delivered without blocking the
// goroutine; cancellation closes the channel. The API client supplies backoff.
func (m *Manager) StartHeartbeat(ctx context.Context, interval time.Duration) <-chan error {
	errorsOut := make(chan error, 1)
	go func() {
		defer close(errorsOut)
		if interval <= 0 {
			errorsOut <- errors.New("heartbeat interval must be positive")
			return
		}
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			if err := m.Heartbeat(ctx); err != nil && ctx.Err() == nil {
				if errors.Is(err, ErrLeaseLost) {
					select {
					case errorsOut <- err:
					case <-ctx.Done():
					}
					return
				}
				select {
				case errorsOut <- err:
				default:
				}
			}
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
		}
	}()
	return errorsOut
}
