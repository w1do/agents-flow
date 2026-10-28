package config

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func fixture(t *testing.T) (string, Config) {
	t.Helper()
	root := t.TempDir()
	dir := filepath.Join(root, "workflow")
	if err := os.Mkdir(dir, 0755); err != nil {
		t.Fatal(err)
	}
	cfg := Config{ServerURL: "https://flow.example.invalid", ProjectID: "project", AgentID: "agent",
		WorkspacePath: root, GitRemote: "origin", PollIntervalSeconds: 5, LeaseTTLSeconds: 60}
	if err := Write(dir, cfg, "private-agent-token"); err != nil {
		t.Fatal(err)
	}
	return root, cfg
}

func TestRoundTrip(t *testing.T) {
	root, want := fixture(t)
	got, token, err := Load(root)
	if err != nil || !reflect.DeepEqual(got, want) || token != "private-agent-token" {
		t.Fatal("configuration did not round trip", err)
	}
	text := testutil.Read(t, filepath.Join(root, "workflow/config.yaml"))
	if strings.Contains(text, "token") {
		t.Fatal("secret stored in YAML")
	}
	info, err := os.Stat(filepath.Join(root, "workflow/.agent-token"))
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("token permissions", err)
	}
}

func TestLoadRejectsInvalidConfig(t *testing.T) {
	for _, content := range []string{
		"agent_token: must-not-be-echoed", "server_url: [", "{}", "server_url: https://user:password@host",
	} {
		t.Run(content, func(t *testing.T) {
			root, _ := fixture(t)
			testutil.Write(t, filepath.Join(root, "workflow/config.yaml"), content)
			_, _, err := Load(root)
			if err == nil || strings.Contains(err.Error(), "must-not-be-echoed") {
				t.Fatal("expected sanitized config error")
			}
		})
	}
}

func TestLoadRejectsUnsafeToken(t *testing.T) {
	for _, value := range []string{"", "one\ntwo", "insecure-mode", "symlink"} {
		t.Run(value, func(t *testing.T) {
			root, _ := fixture(t)
			path := filepath.Join(root, "workflow/.agent-token")
			testutil.Write(t, path, value)
			if value == "insecure-mode" {
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			}
			if value == "symlink" {
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink("config.yaml", path); err != nil {
					t.Fatal(err)
				}
			}
			if _, _, err := Load(root); err == nil {
				t.Fatal("unsafe token accepted")
			}
		})
	}
}

func TestValidate(t *testing.T) {
	_, cfg := fixture(t)
	for _, mutate := range []func(*Config){
		func(c *Config) { c.ServerURL = "file:///tmp/server" },
		func(c *Config) { c.ProjectID = "" },
		func(c *Config) { c.AgentID = "" },
		func(c *Config) { c.WorkspacePath = "relative" },
		func(c *Config) { c.PollIntervalSeconds = 0 },
		func(c *Config) { c.LeaseTTLSeconds = -1 },
	} {
		invalid := cfg
		mutate(&invalid)
		if err := invalid.Validate(); err == nil {
			t.Fatal("invalid configuration accepted")
		}
	}
}
