package agent

import (
	"context"
	"errors"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/leases"
	"agentsflow/harness/internal/workspace"
)

func (e *Engine) runTask(parent context.Context) error {
	claim := e.state.Claim
	if e.leases.State().TaskID == "" {
		if err := e.leases.Resume(leases.State{TaskID: claim.Task.ID, LeaseID: claim.LeaseID}); err != nil {
			return err
		}
	}
	path, err := workspace.Ensure(parent, e.cfg.WorkspacePath, claim.Task.ID)
	if err != nil {
		return err
	}
	e.state.Worktree = path
	if err := e.save(); err != nil {
		return err
	}
	ctx, cancel := context.WithCancelCause(parent)
	e.confirmation.arm(e.state.Pending)
	heartbeatCtx, heartbeatCancel := context.WithCancel(parent)
	beats := e.leases.StartHeartbeat(heartbeatCtx, e.options.HeartbeatInterval)
	joined := make(chan struct{})
	e.heartbeatStop, e.heartbeatDone = heartbeatCancel, joined
	go func() {
		defer close(joined)
		for err := range beats {
			if e.confirmation.confirming(err) {
				continue
			}
			var apiErr *api.Error
			if errors.Is(err, leases.ErrLeaseLost) || errors.As(err, &apiErr) && apiErr.StatusCode < 500 {
				cancel(err)
			}
		}
	}()
	defer func() {
		heartbeatCancel()
		<-joined
		cancel(context.Canceled)
		e.heartbeatStop = nil
		e.heartbeatDone = nil
		e.confirmation.arm(nil)
	}()
	if err := e.flush(ctx); err != nil {
		return err
	}
	if e.state.Stage == "done" {
		return nil
	}
	if err := e.reconcile(ctx); err != nil {
		return err
	}
	for {
		if e.state.Stage == "done" || e.state.Stage == "stopped" {
			return nil
		}
		if ctx.Err() != nil {
			return context.Cause(ctx)
		}
		switch e.state.Stage {
		case "planning", "implementation", "testing", "publication":
			if err := e.execute(ctx); err != nil {
				return err
			}
		case "wait_plan", "wait_result":
			if err := e.waitDecision(ctx); err != nil {
				return err
			}
		default:
			return errors.New("invalid stage in harness run journal")
		}
	}
}

func (e *Engine) execution(ctx context.Context) (api.ExecutionState, error) {
	var state api.ExecutionState
	err := e.retry(ctx, func() error {
		var err error
		state, err = e.api.ExecutionState(ctx, e.state.Claim.Task.ID, e.state.Claim.LeaseID)
		return err
	})
	return state, err
}

// Server state is authoritative when resuming a journal or a server checkpoint.
func (e *Engine) reconcile(ctx context.Context) error {
	state, err := e.execution(ctx)
	if err != nil {
		return err
	}
	switch state.Status {
	case "backlog":
		e.state.Stage = "wait_plan"
	case "ready":
		e.state.Stage = "wait_result"
	case "active":
		if e.state.Stage == "wait_result" {
			e.state.Feedback = state.ResultFeedback
			e.state.Tests = nil
			e.state.ResultData = nil
			e.state.ResultSummary = ""
		} else if e.state.Stage == "wait_plan" || e.state.Stage == "planning" {
			e.state.Feedback = state.PlanFeedback
		}
		if e.state.Stage != "testing" {
			e.state.Stage = "implementation"
		}
	case "testing":
		e.state.Stage = "testing"
	case "merged":
		e.state.Feedback = state.ResultFeedback
		if state.PublicationRequested {
			e.state.Stage = "publication"
		} else {
			e.state.Stage = "done"
		}
	case "planning":
		e.state.Stage = "planning"
		e.state.Feedback = state.PlanFeedback
	case "choosing":
		e.state.Stage = "planning"
	case "trash", "paused", "error", "stalled":
		e.state.Stage = "stopped"
	default:
		return errors.New("unexpected task status")
	}
	return e.save()
}
