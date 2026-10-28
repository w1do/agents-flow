package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadedConfigDetectsChanges(t *testing.T) {
	root, _ := fixture(t)
	cfg, _, err := Load(root)
	if err != nil {
		t.Fatal(err)
	}
	if err := cfg.CheckUnchanged(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "workflow/config.yaml")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(data, []byte("\n# changed\n")...), 0644); err != nil {
		t.Fatal(err)
	}
	if err := cfg.CheckUnchanged(); err == nil || err.Error() != "config changed, restart harness" {
		t.Fatal("expected config change error", err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := cfg.CheckUnchanged(); err == nil {
		t.Fatal("missing config accepted")
	}
}
