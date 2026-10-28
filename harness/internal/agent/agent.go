// Package agent orchestrates the server workflow and an external JSON runner.
package agent

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"time"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/leases"
	"agentsflow/harness/internal/procguard"
	"agentsflow/harness/internal/skills"
)

var (
	ErrRunnerNotConfigured = errors.New("configure runner.command in workflow/config.yaml before run")
	ErrDecisionTimeout     = errors.New("decision wait timed out; task and checkpoint preserved")
)

// Options supplies timing overrides for embedded callers and integration tests.
type Options struct {
	PollInterval, HeartbeatInterval, RetryBackoff, DecisionTimeout time.Duration
}

type Engine struct {
	cfg           config.Config
	agentToken    string
	api           *api.Client
	leases        *leases.Manager
	skills        *skills.Synchronizer
	options       Options
	journal       *journal
	state         durableState
	heartbeatStop context.CancelFunc
	heartbeatDone <-chan struct{}
	confirmation  confirmationGate
}

func Run(ctx context.Context, cfg config.Config, token string) error {
	engine, err := New(cfg, token, Options{})
	if err != nil {
		return err
	}
	return engine.Run(ctx)
}

func New(cfg config.Config, token string, options Options) (*Engine, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	if !procguard.Supported {
		return nil, errors.New("runner supervision requires Linux")
	}
	if len(cfg.Runner.Command) == 0 {
		return nil, ErrRunnerNotConfigured
	}
	command := append([]string(nil), cfg.Runner.Command...)
	if strings.ContainsRune(command[0], filepath.Separator) && !filepath.IsAbs(command[0]) {
		command[0] = filepath.Join(cfg.WorkspacePath, command[0])
	}
	cfg.Runner.Command = command
	client, err := api.New(cfg.ServerURL, token, api.Options{AllowInsecure: cfg.AllowInsecure})
	if err != nil {
		return nil, err
	}
	if options.PollInterval <= 0 {
		options.PollInterval = time.Duration(cfg.PollIntervalSeconds) * time.Second
	}
	if options.HeartbeatInterval <= 0 {
		options.HeartbeatInterval = time.Duration(cfg.LeaseTTLSeconds) * time.Second / 3
	}
	if options.RetryBackoff <= 0 {
		options.RetryBackoff = 200 * time.Millisecond
	}
	if options.DecisionTimeout <= 0 {
		options.DecisionTimeout = time.Hour
		if cfg.Runner.DecisionTimeoutSeconds > 0 {
			options.DecisionTimeout = time.Duration(cfg.Runner.DecisionTimeoutSeconds) * time.Second
		}
	}
	return &Engine{cfg: cfg, agentToken: token, api: client, leases: leases.New(client, cfg.AgentID), options: options,
		skills: skills.New(filepath.Join(cfg.WorkspacePath, "workflow", "skills"), cfg.AgentID, client)}, nil
}
