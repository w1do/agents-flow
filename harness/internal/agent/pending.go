package agent

import (
	"errors"

	"agentsflow/harness/internal/jsonx"
)

func validatePending(state durableState) error {
	pending := state.Pending
	if pending == nil {
		return nil
	}
	next, known := map[string]string{"events": "", "plan": "wait_plan", "result": "wait_result", "fail": "done", "publication-result": "done"}[pending.Kind]
	if !known || next != pending.Next || pending.Key == "" || state.Claim == nil {
		return errors.New("invalid pending report identity in run journal")
	}
	var body struct {
		EventID string `json:"event_id"`
		LeaseID string `json:"lease_id"`
	}
	if jsonx.Unmarshal(pending.Body, &body) != nil || body.EventID != pending.Key || body.LeaseID == "" || body.LeaseID != state.Claim.LeaseID {
		return errors.New("pending report identity does not match its immutable body")
	}
	return nil
}
