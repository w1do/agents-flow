package gitrepo

import (
	"context"
	"reflect"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestRunDropsInheritedGitConfiguration(t *testing.T) {
	root := testutil.Repository(t)
	t.Setenv("GIT_DIR", "/missing-fixture")
	t.Setenv("GIT_CONFIG_COUNT", "1")
	t.Setenv("GIT_CONFIG_KEY_0", "core.bare")
	t.Setenv("GIT_CONFIG_VALUE_0", "true")
	got, err := Root(context.Background(), root)
	if err != nil || got != root {
		t.Fatal("inherited Git environment changed repository discovery", err)
	}
	cmd := command(context.Background(), root, nil, "status")
	env := strings.Join(cmd.Env, "\n")
	for _, value := range []string{
		"GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_SYSTEM=/dev/null",
		"GIT_TERMINAL_PROMPT=0", "GIT_ASKPASS=/bin/true", "GIT_PAGER=cat", "GIT_LITERAL_PATHSPECS=1",
	} {
		if !strings.Contains(env, value+"\n") && !strings.HasSuffix(env, value) {
			t.Fatal("missing isolated environment setting", value)
		}
	}
}

func TestNeutralFiltersHandlesNamesWithDots(t *testing.T) {
	got := neutralFilters("filter.audit.with.dots.smudge\x00filter.audit.with.dots.clean\x00")
	want := []string{"-c", "filter.audit.with.dots.clean=cat", "-c", "filter.audit.with.dots.smudge=cat",
		"-c", "filter.audit.with.dots.process=", "-c", "filter.audit.with.dots.required=false"}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("filter overrides differ", got)
	}
}
