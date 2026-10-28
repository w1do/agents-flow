package config

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentsflow/harness/internal/api"
	"gopkg.in/yaml.v3"
)

type Config struct {
	ServerURL           string `yaml:"server_url"`
	ProjectID           string `yaml:"project_id"`
	AgentID             string `yaml:"agent_id"`
	WorkspacePath       string `yaml:"workspace_path"`
	GitRemote           string `yaml:"git_remote"`
	AllowInsecure       bool   `yaml:"allow_insecure,omitempty"`
	PollIntervalSeconds int    `yaml:"poll_interval_seconds"`
	LeaseTTLSeconds     int    `yaml:"lease_ttl_seconds"`
	Runner              Runner `yaml:"runner,omitempty"`
}

func (c Config) Validate() error {
	if err := api.ValidateURLWithInsecure(c.ServerURL, c.AllowInsecure); err != nil {
		return err
	}
	if strings.TrimSpace(c.ProjectID) == "" || strings.TrimSpace(c.AgentID) == "" ||
		!filepath.IsAbs(c.WorkspacePath) || c.PollIntervalSeconds <= 0 || c.LeaseTTLSeconds <= 0 {
		return errors.New("config requires project_id, agent_id, absolute workspace_path and positive intervals")
	}
	return c.Runner.validate()
}

func Load(root string) (Config, string, error) {
	var cfg Config
	dir := filepath.Join(root, "workflow")
	data, err := os.ReadFile(filepath.Join(dir, "config.yaml"))
	if err != nil {
		return cfg, "", errors.New("cannot read workflow/config.yaml; run harness init first")
	}
	decoder := yaml.NewDecoder(strings.NewReader(string(data)))
	decoder.KnownFields(true)
	if err := decoder.Decode(&cfg); err != nil {
		return cfg, "", errors.New("invalid workflow/config.yaml")
	}
	if err := decoder.Decode(new(any)); !errors.Is(err, io.EOF) {
		return cfg, "", errors.New("config must contain a single YAML document")
	}
	if err := cfg.Validate(); err != nil {
		return cfg, "", err
	}
	path := filepath.Join(dir, ".agent-token")
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 {
		return cfg, "", errors.New("workflow/.agent-token must be a regular file with permissions 0600")
	}
	data, err = os.ReadFile(path)
	if err != nil {
		return cfg, "", errors.New("cannot read workflow/.agent-token")
	}
	token := strings.TrimSpace(string(data))
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return cfg, "", errors.New("invalid workflow/.agent-token")
	}
	return cfg, token, nil
}

// Write writes into a newly created workflow directory owned by the initializer.
func Write(dir string, cfg Config, token string) error {
	if err := cfg.Validate(); err != nil {
		return err
	}
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return errors.New("invalid agent token in init response")
	}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return errors.New("cannot encode config")
	}
	for _, file := range []struct {
		name string
		data []byte
		mode os.FileMode
	}{
		{".gitignore", []byte(".agent-token\n"), 0644},
		{"config.yaml", data, 0644},
		{".agent-token", []byte(token + "\n"), 0600},
	} {
		f, err := os.OpenFile(filepath.Join(dir, file.name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, file.mode)
		if err != nil {
			return err
		}
		modeErr := f.Chmod(file.mode)
		_, writeErr := f.Write(file.data)
		closeErr := f.Close()
		if err := errors.Join(modeErr, writeErr, closeErr); err != nil {
			return err
		}
	}
	return nil
}
