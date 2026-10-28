package bootstrap

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/gitrepo"
	"agentsflow/harness/internal/skills"
)

type Options struct {
	Directory, ServerURL, ProjectID, AgentName string
	ReadCode                                   func() (string, error)
}

func Init(ctx context.Context, options Options) error {
	return InitWithInsecure(ctx, options, false)
}

func InitWithInsecure(ctx context.Context, options Options, allowInsecure bool) error {
	root, err := gitrepo.Root(ctx, options.Directory)
	if err != nil {
		return err
	}
	dir := filepath.Join(root, "workflow")
	if _, err := os.Lstat(dir); err == nil || !os.IsNotExist(err) {
		return errors.New("workflow already exists or cannot be accessed; refusing to overwrite it")
	}
	remote, err := gitrepo.Origin(ctx, root)
	if err != nil {
		return err
	}
	client, err := api.New(options.ServerURL, "", api.Options{AllowInsecure: allowInsecure})
	if err != nil {
		return err
	}
	if strings.TrimSpace(options.ProjectID) == "" || strings.TrimSpace(options.AgentName) == "" {
		return errors.New("project_id and agent_name are required")
	}
	if options.ReadCode == nil {
		return errors.New("init code reader is required")
	}
	code, err := options.ReadCode()
	if err != nil || strings.TrimSpace(code) == "" {
		return errors.New("an init code is required via stdin or AGENTS_FLOW_INIT_TOKEN")
	}
	result, err := client.Init(ctx, api.InitRequest{
		ProjectID: options.ProjectID, InitCode: strings.TrimSpace(code), AgentName: options.AgentName,
		RepositoryPathHint: root, GitRemote: remote,
	})
	if err != nil {
		return err
	}
	if result.ServerURL == "" {
		result.ServerURL = options.ServerURL
	}
	cfg := config.Config{
		ServerURL: result.ServerURL, ProjectID: options.ProjectID, AgentID: result.AgentID,
		WorkspacePath: root, GitRemote: "origin", PollIntervalSeconds: result.PollIntervalSeconds,
		LeaseTTLSeconds: result.LeaseTTLSeconds,
		AllowInsecure:   allowInsecure,
	}
	if err := cfg.Validate(); err != nil {
		return err
	}
	if err := os.Mkdir(dir, 0755); err != nil {
		return err
	}
	complete := false
	defer func() {
		if !complete {
			_ = os.RemoveAll(dir)
		}
	}()
	if err := config.Write(dir, cfg, result.AgentToken); err != nil {
		return err
	}
	if err := skills.Apply(filepath.Join(dir, "skills"), result.Skills); err != nil {
		return err
	}
	complete = true
	return nil
}
