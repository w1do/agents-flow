package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
)

type ExecutionState struct {
	TaskID               string          `json:"task_id"`
	LeaseID              string          `json:"lease_id"`
	Status               string          `json:"status"`
	PlanDecision         string          `json:"plan_decision"`
	PlanFeedback         string          `json:"plan_feedback"`
	ResultDecision       string          `json:"result_decision"`
	ResultFeedback       string          `json:"result_feedback"`
	PublicationRequested bool            `json:"publication_requested"`
	Checkpoint           json.RawMessage `json:"checkpoint"`
}

func TaskPath(id, suffix string) string {
	return "/api/v1/tasks/" + url.PathEscape(id) + "/" + suffix
}

func (c *Client) ExecutionState(ctx context.Context, task, lease string) (ExecutionState, error) {
	var state ExecutionState
	_, err := c.Request(ctx, http.MethodGet,
		TaskPath(task, "execution-state")+"?lease_id="+url.QueryEscape(lease), "", nil, &state)
	if err == nil && (state.TaskID != task || state.LeaseID != lease || state.Status == "") {
		err = fmt.Errorf("invalid execution-state response")
	}
	return state, err
}
