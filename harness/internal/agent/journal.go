package agent

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"syscall"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/gitrepo"
	"agentsflow/harness/internal/jsonx"
)

type durableState struct {
	ClaimSnapshot, RuntimeSnapshot  string
	ResultSummary                   string
	ResultData                      map[string]any
	AgentID, ServerURL, ClaimKey    string
	Claim                           *api.ClaimResponse
	Stage, Worktree, Plan, Feedback string
	Checkpoint                      json.RawMessage
	Tests                           []json.RawMessage
	TestsTruncated                  bool
	Pending                         *pendingReport
	Lost                            bool
}

type pendingReport struct {
	Kind string          `json:"kind"`
	Key  string          `json:"event_id"`
	Next string          `json:"next"`
	Body json.RawMessage `json:"body"`
}

type journal struct {
	dir  string
	lock *os.File
}

func openJournal(ctx context.Context, root string) (*journal, error) {
	gitDir, err := gitrepo.Run(ctx, root, "rev-parse", "--absolute-git-dir")
	if err != nil {
		return nil, err
	}
	dir := filepath.Join(gitDir, "agents-flow-harness")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	lock, err := os.OpenFile(filepath.Join(dir, "run.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lock.Close()
		return nil, errors.New("harness run is already active for this repository")
	}
	return &journal{dir, lock}, nil
}

func (j *journal) close() { _ = j.lock.Close() }

func (j *journal) load() (durableState, error) {
	var state durableState
	data, err := os.ReadFile(filepath.Join(j.dir, "state.json"))
	if os.IsNotExist(err) {
		return state, nil
	}
	if err != nil {
		return state, err
	}
	if err := jsonx.Unmarshal(data, &state); err != nil {
		return state, errors.New("invalid harness run journal")
	}
	state, err = j.restore(state)
	if err != nil {
		return state, err
	}
	return state, validatePending(state)
}

func (j *journal) save(state durableState, knownToken ...string) error {
	token := ""
	if len(knownToken) != 0 {
		token = knownToken[0]
	}
	return j.saveSnapshot(state, token)
}

func (e *Engine) save() error { return e.journal.save(e.state, e.agentToken) }
