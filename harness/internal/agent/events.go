package agent

import (
	"context"
	"encoding/json"
	"strings"

	"agentsflow/harness/internal/jsonx"
)

func (e *Engine) consume(ctx context.Context, event runnerEvent, terminal **runnerEvent) error {
	if len(event.Checkpoint) > 0 && string(event.Checkpoint) != "null" {
		var object map[string]json.RawMessage
		if jsonx.Unmarshal(event.Checkpoint, &object) != nil {
			return errRunnerProtocol
		}
		e.state.Checkpoint = sanitizeJSONWithToken(event.Checkpoint, e.agentToken)
		if err := e.save(); err != nil {
			return eventReportError{err}
		}
		if err := e.checkpointEvent(ctx, "progress", "Checkpoint", nil); err != nil {
			return eventReportError{err}
		}
	}
	switch event.Type {
	case "plan", "result":
		if *terminal != nil || event.Type == "plan" && e.state.Stage != "planning" || event.Type == "result" && e.state.Stage == "planning" {
			return errRunnerProtocol
		}
		if event.Type == "plan" && strings.TrimSpace(event.PlanText) == "" {
			return errRunnerProtocol
		}
		*terminal = &event
		return nil
	case "progress":
		if err := e.checkpointEvent(ctx, "progress", event.Message, map[string]any{"details": event.Payload}); err != nil {
			return eventReportError{err}
		}
		return nil
	case "test_result":
		payload := map[string]any{"command": event.Command, "exit_code": event.ExitCode, "summary": event.Summary, "details": event.Payload}
		data, _ := json.Marshal(payload)
		data = sanitizeJSONWithToken(data, e.agentToken)
		if len(data) > maxTestBytes {
			data = []byte(`{"truncated":true,"message":"test_result exceeded size limit"}`)
		}
		if bytesContains(data, []byte(`"truncated":true`)) {
			payload = map[string]any{"truncated": true, "message": "test_result exceeded size limit"}
		} else {
			_ = jsonx.Unmarshal(data, &payload)
		}
		e.state.Tests = append(e.state.Tests, data)
		oldCount := len(e.state.Tests)
		for len(e.state.Tests) > maxTestEvents {
			e.state.Tests = e.state.Tests[1:]
		}
		for testsSize(e.state.Tests) > maxTestBytes && len(e.state.Tests) > 1 {
			e.state.Tests = e.state.Tests[1:]
		}
		if len(e.state.Tests) != oldCount {
			e.state.TestsTruncated = true
		}
		if err := e.checkpointEvent(ctx, "test_result", event.Message, payload); err != nil {
			return eventReportError{err}
		}
		return nil
	case "failure":
		return errRunnerFailed
	default:
		return errRunnerProtocol
	}
}

func testsSize(tests []json.RawMessage) int {
	n := 0
	for _, test := range tests {
		n += len(test)
	}
	return n
}
func bytesContains(data, part []byte) bool { return strings.Contains(string(data), string(part)) }

func (e *Engine) finish(ctx context.Context, event runnerEvent) error {
	switch e.state.Stage {
	case "planning":
		e.state.Plan = event.PlanText
		if err := e.report(ctx, "plan", "wait_plan", map[string]any{"plan_text": event.PlanText}); err != nil {
			return err
		}
		return e.checkpointEvent(ctx, "progress", "Waiting for plan decision", nil)
	case "implementation":
		e.state.ResultSummary, e.state.ResultData = event.ResultSummary, event.ResultData
		e.state.Stage = "testing"
		return e.checkpointEvent(ctx, "progress", "Implementation complete", nil)
	case "testing":
		data := e.state.ResultData
		if data == nil {
			data = map[string]any{}
		}
		for key, value := range event.ResultData {
			data[key] = value
		}
		data["tests"] = e.state.Tests
		e.state.ResultData = data
		if e.state.TestsTruncated {
			data["tests_truncated"] = true
		}
		summary := event.ResultSummary
		if summary == "" {
			summary = e.state.ResultSummary
		}
		if err := e.report(ctx, "result", "wait_result", map[string]any{"result_summary": summary, "result_data": data}); err != nil {
			return err
		}
		return e.checkpointEvent(ctx, "progress", "Waiting for result decision", nil)
	case "publication":
		if event.Success == nil {
			return e.report(ctx, "publication-result", "done", map[string]any{"success": false, "message": "Publication runner omitted success"})
		}
		return e.report(ctx, "publication-result", "done", map[string]any{"success": *event.Success, "message": event.Message, "payload": event.ResultData})
	}
	return errRunnerProtocol
}
