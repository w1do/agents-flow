package agent

import (
	"context"
	"errors"
)

func (e *Engine) waitDecision(parent context.Context) error {
	ctx, cancel := context.WithTimeout(parent, e.options.DecisionTimeout)
	defer cancel()
	for {
		state, err := e.execution(ctx)
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) && parent.Err() == nil {
				return ErrDecisionTimeout
			}
			return err
		}
		next := ""
		if state.Status == "trash" || state.Status == "paused" || state.Status == "error" || state.Status == "stalled" {
			next = "stopped"
		} else if e.state.Stage == "wait_plan" {
			switch state.PlanDecision {
			case "approved":
				if state.Status == "active" {
					next = "implementation"
				}
			case "rejected":
				if state.Status == "planning" {
					next = "planning"
				}
			case "trash":
				next = "stopped"
			}
			e.state.Feedback = state.PlanFeedback
		} else {
			switch {
			case state.PublicationRequested && state.Status == "merged":
				next = "publication"
			case state.Status == "active":
				next = "implementation"
				e.state.Feedback = state.ResultFeedback
				e.state.Tests = nil
				e.state.ResultData = nil
				e.state.ResultSummary = ""
			case state.Status == "merged" && !state.PublicationRequested:
				next = "done"
				// keep_ready parks here, keeping heartbeat alive for a later decision.
			}
		}
		if next != "" {
			e.state.Stage = next
			return e.save()
		}
		if err := sleep(ctx, e.options.PollInterval); err != nil {
			if parent.Err() == nil && errors.Is(err, context.DeadlineExceeded) {
				return ErrDecisionTimeout
			}
			return err
		}
	}
}
