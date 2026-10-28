package agent

import (
	"context"
	"errors"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/leases"
)

func (e *Engine) Run(ctx context.Context) error {
	j, err := openJournal(ctx, e.cfg.WorkspacePath)
	if err != nil {
		return err
	}
	defer j.close()
	e.journal = j
	e.state, err = j.load()
	if err != nil {
		return err
	}
	if e.state.AgentID != "" && (e.state.AgentID != e.cfg.AgentID || e.state.ServerURL != e.cfg.ServerURL) {
		return errors.New("run journal belongs to another agent or server")
	}
	if e.state.Lost || e.state.Stage == "done" {
		e.state = durableState{}
	}
	e.state.AgentID, e.state.ServerURL = e.cfg.AgentID, e.cfg.ServerURL
	e.leases.Release()
	e.skills.SetActive(false)
	for ctx.Err() == nil {
		if e.state.Claim == nil {
			if err := e.waitClaim(ctx); err != nil {
				return err
			}
		}
		e.skills.SetActive(true)
		err := e.runTask(ctx)
		if errors.Is(err, leases.ErrLeaseLost) {
			e.state.Lost = true
			if saveErr := e.save(); saveErr != nil {
				return saveErr
			}
		}
		if err != nil {
			return err
		}
		if e.state.Stage != "done" {
			return nil
		}
		e.state = durableState{AgentID: e.cfg.AgentID, ServerURL: e.cfg.ServerURL}
		if err := e.save(); err != nil {
			return err
		}
		e.leases.Release()
		e.skills.SetActive(false)
	}
	return context.Cause(ctx)
}

func (e *Engine) acquire(ctx context.Context) (bool, error) {
	if e.state.ClaimKey == "" {
		if err := e.retry(ctx, func() error { return e.skills.Sync(ctx) }); err != nil {
			return false, err
		}
		e.state.ClaimKey = api.NewKey()
		if err := e.save(); err != nil {
			return false, err
		}
	}
	e.leases.PrepareClaim(e.state.ClaimKey)
	claim, err := e.leases.Claim(ctx)
	if err != nil {
		return false, err
	}
	e.state.ClaimKey = ""
	if claim != nil {
		e.state.Claim = claim
		e.state.Stage = "planning"
		e.state.Plan = claim.Task.PlanText
		e.restoreCheckpoint(claim.Task.Checkpoint)
	}
	return claim != nil, e.save()
}
