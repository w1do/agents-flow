package agent

import (
	"encoding/json"
	"errors"
	"os"

	"agentsflow/harness/internal/atomicfs"
)

func (j *journal) restore(state durableState) (durableState, error) {
	if state.RuntimeSnapshot == "" {
		return state, nil
	} // Read pre-snapshot journals.
	blobs, err := openSnapshots(j.dir)
	if err != nil {
		return state, err
	}
	defer blobs.root.Close()
	var full durableState
	if err := blobs.get(state.RuntimeSnapshot, &full); err != nil {
		return state, err
	}
	if full.ClaimSnapshot != state.ClaimSnapshot || full.AgentID != state.AgentID || full.ServerURL != state.ServerURL {
		return state, errors.New("journal snapshot identity mismatch")
	}
	if full.ClaimSnapshot != "" {
		if err := blobs.get(full.ClaimSnapshot, &full.Claim); err != nil {
			return state, err
		}
	}
	return full, nil
}

func (j *journal) saveSnapshot(state durableState, token string) error {
	blobs, err := openSnapshots(j.dir)
	if err != nil {
		return err
	}
	defer blobs.root.Close()
	claimRef := ""
	if state.Claim != nil {
		claimRef, err = blobs.put(state.Claim, token)
		if err != nil {
			return err
		}
	}
	// Only value copies are edited. No limiter may touch shared claim/pending
	// pointers, slices or maps belonging to the running task.
	runtimeState := state
	runtimeState.Claim = nil
	runtimeState.ClaimSnapshot = claimRef
	runtimeState.RuntimeSnapshot = ""
	runtimeRef, err := blobs.put(runtimeState, token)
	if err != nil {
		return err
	}
	compact := compactJournal(state, claimRef, runtimeRef)
	data, err := json.Marshal(compact)
	if err != nil {
		return errors.New("cannot encode harness run journal")
	}
	data = sanitizeJSONWithToken(data, token)
	if len(data) > maxReportBytes {
		return errors.New("compact journal exceeds size limit")
	}
	root, err := os.OpenRoot(j.dir)
	if err != nil {
		return err
	}
	defer root.Close()
	if err := atomicfs.Write(root, "state.json", data, 0600); err != nil {
		return err
	}
	// Both blobs and the directory entry are durable before removing old data.
	blobs.collect(claimRef, runtimeRef)
	return nil
}
