package agent

import (
	"context"
	"errors"
	"time"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/leases"
)

func sleep(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return context.Cause(ctx)
	case <-timer.C:
		return nil
	}
}

func retryable(err error) bool {
	var changed *config.ChangedError
	if errors.As(err, &changed) {
		return false
	}
	var serverErr *api.Error
	return !errors.As(err, &serverErr) || serverErr.StatusCode >= 500 || serverErr.StatusCode == 429
}

func (e *Engine) retry(ctx context.Context, operation func() error) error {
	delay := e.options.RetryBackoff
	for {
		if ctx.Err() != nil {
			return context.Cause(ctx)
		}
		err := operation()
		if err == nil {
			return nil
		}
		var serverErr *api.Error
		if errors.As(err, &serverErr) && serverErr.StatusCode == 409 {
			return leases.ErrLeaseLost
		}
		if !retryable(err) {
			return err
		}
		if err := sleep(ctx, delay); err != nil {
			return err
		}
		delay = min(2*delay, 5*time.Second)
	}
}
