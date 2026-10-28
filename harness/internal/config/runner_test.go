package config

import (
	"path/filepath"
	"reflect"
	"testing"

	"agentsflow/harness/internal/testutil"
	"gopkg.in/yaml.v3"
)

func TestRunnerConfigRoundTrip(t *testing.T) {
	root, cfg := fixture(t)
	cfg.Runner = Runner{Command: []string{"/path with spaces/runner", "argument with spaces"}, TimeoutSeconds: 120, DecisionTimeoutSeconds: 300}
	data, err := yaml.Marshal(cfg)
	if err != nil {
		t.Fatal(err)
	}
	testutil.Write(t, filepath.Join(root, "workflow/config.yaml"), string(data))
	got, _, err := Load(root)
	if err != nil || !reflect.DeepEqual(got, cfg) {
		t.Fatal("runner configuration did not round trip", err)
	}
}

func TestInvalidRunnerConfig(t *testing.T) {
	for _, runner := range []Runner{{Command: []string{" "}}, {TimeoutSeconds: -1}, {DecisionTimeoutSeconds: -1}} {
		_, cfg := fixture(t)
		cfg.Runner = runner
		if err := cfg.Validate(); err == nil {
			t.Fatal("invalid runner configuration accepted")
		}
	}
}
