package agent

import (
	"context"
	"errors"
	"time"
)

type eventReportError struct{ error }

func (e *Engine) execute(ctx context.Context) error {
	state, err := e.execution(ctx)
	if err != nil {
		return err
	}
	switch e.state.Stage {
	case "planning":
		if state.Status != "choosing" && state.Status != "planning" {
			return e.reconcile(ctx)
		}
		if state.Status == "choosing" {
			if err := e.checkpointEvent(ctx, "planning", "Planning", nil); err != nil {
				return err
			}
		}
	case "implementation":
		if state.Status != "active" || state.PlanDecision != "approved" {
			return e.reconcile(ctx)
		}
	case "testing":
		if state.Status != "active" && state.Status != "testing" {
			return e.reconcile(ctx)
		}
		if state.Status == "active" {
			if err := e.checkpointEvent(ctx, "testing", "Testing", nil); err != nil {
				return err
			}
		}
	case "publication":
		if state.Status != "merged" || !state.PublicationRequested {
			return e.reconcile(ctx)
		}
		if len(stageSkills(e.state.Claim.Skills, "publication")) == 0 {
			return e.report(ctx, "publication-result", "done", map[string]any{"success": false, "message": "No publication skills assigned"})
		}
	}
	for _, skill := range stageSkills(e.state.Claim.Skills, e.state.Stage) {
		if skill.SnapshotContentMissing {
			if e.state.Stage == "publication" {
				return e.report(ctx, "publication-result", "done", map[string]any{"success": false, "message": "Publication skill snapshot is missing"})
			}
			return e.report(ctx, "fail", "done", map[string]any{"message": "Claim is missing required skill snapshot content"})
		}
	}
	if err := e.checkpointEvent(ctx, "progress", "Starting "+e.state.Stage, nil); err != nil {
		return err
	}
	timeout := 30 * time.Minute
	if e.cfg.Runner.TimeoutSeconds > 0 {
		timeout = time.Duration(e.cfg.Runner.TimeoutSeconds) * time.Second
	}
	runnerCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var terminal *runnerEvent
	err = runProcess(runnerCtx, e.cfg.Runner.Command, e.input(), e.cfg.Runner.Environment, func(event runnerEvent) error {
		return e.consume(runnerCtx, event, &terminal)
	})
	if ctx.Err() != nil {
		return context.Cause(ctx)
	}
	var reportErr eventReportError
	if errors.As(err, &reportErr) {
		return reportErr.error
	}
	if err != nil {
		if !errors.Is(err, errRunnerFailed) && !errors.Is(err, errRunnerProtocol) && !errors.Is(err, context.DeadlineExceeded) {
			return err
		}
		if e.state.Stage == "publication" {
			return e.report(ctx, "publication-result", "done", map[string]any{"success": false, "message": "Publication runner failed"})
		}
		return e.report(ctx, "fail", "done", map[string]any{"message": "Runner failed; checkpoint preserved"})
	}
	if terminal == nil {
		if e.state.Stage == "publication" {
			return e.report(ctx, "publication-result", "done", map[string]any{"success": false, "message": "Publication runner exited without a terminal event"})
		}
		return e.report(ctx, "fail", "done", map[string]any{"message": "Runner exited without a terminal event"})
	}
	return e.finish(ctx, *terminal)
}
