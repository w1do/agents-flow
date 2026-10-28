package agent

import (
	"context"
	"errors"
	"time"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/leases"
)

// Idle heartbeats do not suppress replay of a previously accepted claim key.
// The idle worker is joined before starting heartbeats for the claimed task.
func (e *Engine) waitClaim(parent context.Context) error {
	ctx, cancel := context.WithCancelCause(parent)
	joined := make(chan struct{})
	go func() {
		defer close(joined)
		for {
			_, err := e.api.Heartbeat(ctx, e.cfg.AgentID, api.HeartbeatRequest{})
			var serverErr *api.Error
			if errors.As(err, &serverErr) && serverErr.StatusCode < 500 && serverErr.StatusCode != 429 {
				cancel(err)
				return
			}
			if sleep(ctx, e.options.HeartbeatInterval) != nil {
				return
			}
		}
	}()
	defer func() { cancel(context.Canceled); <-joined }()
	delay := e.options.RetryBackoff
	for ctx.Err() == nil {
		active, err := e.acquire(ctx)
		if err != nil {
			if !retryable(err) && !errors.Is(err, leases.ErrBusy) {
				return err
			}
			if errors.Is(err, leases.ErrBusy) {
				_ = e.leases.Heartbeat(ctx)
			}
			if err := sleep(ctx, delay); err != nil {
				return err
			}
			delay = min(2*delay, 5*time.Second)
			continue
		}
		if active {
			return nil
		}
		delay = e.options.RetryBackoff
		if err := sleep(ctx, e.options.PollInterval); err != nil {
			return err
		}
	}
	return context.Cause(ctx)
}
