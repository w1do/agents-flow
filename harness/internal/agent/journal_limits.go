package agent

import (
	"encoding/json"

	"agentsflow/harness/internal/api"
)

func compactJournal(state durableState, claimRef, runtimeRef string) durableState {
	compact := durableState{AgentID: state.AgentID, ServerURL: state.ServerURL, ClaimKey: state.ClaimKey,
		Stage: state.Stage, Worktree: state.Worktree, Lost: state.Lost, ClaimSnapshot: claimRef, RuntimeSnapshot: runtimeRef}
	if state.Claim != nil {
		compact.Claim = &api.ClaimResponse{Task: api.Task{ID: state.Claim.Task.ID},
			LeaseID: state.Claim.LeaseID, LeaseExpiresAt: state.Claim.LeaseExpiresAt}
	}
	if state.Pending != nil {
		compact.Pending = &pendingReport{Kind: state.Pending.Kind, Key: state.Pending.Key, Next: state.Pending.Next}
	}
	// A bounded diagnostic preview is optional; restoration always uses the
	// complete snapshot, never these compact fields.
	if len(state.Checkpoint) <= maxCheckpointBytes {
		compact.Checkpoint = state.Checkpoint
	} else {
		compact.Checkpoint = json.RawMessage(`{"truncated":true}`)
	}
	return compact
}
