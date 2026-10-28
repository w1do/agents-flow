package agent

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/jsonx"
)

func (e *Engine) report(ctx context.Context, kind, next string, body map[string]any) error {
	if e.state.Pending != nil {
		return errors.New("an earlier report is still pending")
	}
	key := api.NewKey()
	body["lease_id"], body["event_id"] = e.state.Claim.LeaseID, key
	data, err := json.Marshal(body)
	if err != nil {
		return errors.New("cannot encode runner report")
	}
	data = truncateReport(sanitizeJSONWithToken(data, e.agentToken))
	e.state.Pending = &pendingReport{Kind: kind, Key: key, Next: next, Body: data}
	if err := e.save(); err != nil {
		return err
	}
	return e.flush(ctx)
}

func (e *Engine) stopHeartbeat() {
	if e.heartbeatStop == nil {
		return
	}
	e.heartbeatStop()
	if e.heartbeatDone != nil {
		<-e.heartbeatDone
	}
	e.heartbeatStop, e.heartbeatDone = nil, nil
}

func (e *Engine) flush(ctx context.Context) error {
	if err := validatePending(e.state); err != nil {
		return err
	}
	pending := e.state.Pending
	if pending == nil {
		return nil
	}
	e.confirmation.arm(pending)
	if err := e.retry(ctx, func() error {
		_, err := e.api.Request(ctx, http.MethodPost, api.TaskPath(e.state.Claim.Task.ID, pending.Kind),
			pending.Key, pending.Body, nil)
		return err
	}); err != nil {
		return err
	}
	if pending.Next == "done" {
		e.stopHeartbeat()
	}
	if pending.Next != "" {
		e.state.Stage = pending.Next
	}
	e.state.Pending = nil
	if err := e.save(); err != nil {
		return err
	}
	return nil
}

type checkpoint struct {
	Harness struct {
		ResultSummary  string            `json:"result_summary,omitempty"`
		ResultData     map[string]any    `json:"result_data,omitempty"`
		Stage          string            `json:"stage"`
		Worktree       string            `json:"worktree"`
		Plan           string            `json:"plan_text,omitempty"`
		Tests          []json.RawMessage `json:"tests,omitempty"`
		TestsTruncated bool              `json:"tests_truncated,omitempty"`
	} `json:"harness"`
	Runner json.RawMessage `json:"runner"`
}

func (e *Engine) checkpoint() checkpoint {
	var value checkpoint
	value.Harness.Stage = e.state.Stage
	value.Harness.Worktree = e.state.Worktree
	value.Harness.Plan = e.state.Plan
	value.Harness.Tests = e.state.Tests
	value.Harness.TestsTruncated = e.state.TestsTruncated
	value.Harness.ResultSummary = e.state.ResultSummary
	value.Harness.ResultData = e.state.ResultData
	value.Runner = e.state.Checkpoint
	return value
}

func (e *Engine) restoreCheckpoint(raw json.RawMessage) {
	if len(raw) == 0 || string(raw) == "null" {
		return
	}
	var value checkpoint
	if jsonx.Unmarshal(raw, &value) == nil && value.Harness.Stage != "" {
		e.state.Stage = value.Harness.Stage
		if value.Harness.Plan != "" {
			e.state.Plan = value.Harness.Plan
		}
		e.state.Tests = value.Harness.Tests
		e.state.ResultSummary = value.Harness.ResultSummary
		e.state.ResultData = value.Harness.ResultData
		e.state.Checkpoint = value.Runner
	} else {
		e.state.Checkpoint = raw
	}
}

func (e *Engine) checkpointEvent(ctx context.Context, eventType, message string, payload any) error {
	return e.report(ctx, "events", "", map[string]any{"event_type": eventType, "message": message,
		"payload": payload, "checkpoint": e.checkpoint()})
}
