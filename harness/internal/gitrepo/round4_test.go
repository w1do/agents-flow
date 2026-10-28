package gitrepo

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestLateWorktreeAndIncludedFiltersAreNeutralized(t *testing.T) {
	for _, scope := range []string{"worktree", "local", "global"} {
		t.Run(scope, func(t *testing.T) {
			root := testutil.Repository(t)
			ctx := context.Background()
			if _, err := Run(ctx, root, "status", "--porcelain"); err != nil {
				t.Fatal(err)
			}
			testutil.Git(t, root, "config", "extensions.worktreeConfig", "true")
			config := filepath.Join(t.TempDir(), "included")
			body := "[filter \"late\"]\nclean = \"touch filter-ran; cat\"\nprocess = \"touch filter-ran; false\"\nrequired = true\n"
			if err := os.WriteFile(config, []byte(body), 0600); err != nil {
				t.Fatal(err)
			}
			if scope == "global" {
				home := t.TempDir()
				t.Setenv("HOME", home)
				if err := os.WriteFile(filepath.Join(home, ".gitconfig"), []byte(body), 0600); err != nil {
					t.Fatal(err)
				}
			} else {
				testutil.Git(t, root, "config", "--"+scope, "include.path", config)
			}
			for path, data := range map[string]string{".gitattributes": "*.txt filter=late\n", "note.txt": "changed\n"} {
				if err := os.WriteFile(filepath.Join(root, path), []byte(data), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := Run(ctx, root, "add", "note.txt"); err != nil {
				t.Fatal(err)
			}
			if _, err := os.Stat(filepath.Join(root, "filter-ran")); !os.IsNotExist(err) {
				t.Fatal("filter executed")
			}
			options, err := filterOptions(ctx, root)
			if err != nil || !strings.Contains(strings.Join(options, " "), "filter.late.clean=cat") {
				t.Fatal("scope not discovered", err)
			}
		})
	}
}

func TestGitTransportAndExcludesAreDisabled(t *testing.T) {
	root := testutil.Repository(t)
	cmd := command(context.Background(), root, nil, "log")
	if !strings.Contains(strings.Join(cmd.Env, "\n"), "GIT_NO_LAZY_FETCH=1") {
		t.Fatal("lazy fetching enabled")
	}
	for _, option := range []string{"core.sshCommand=/bin/false", "protocol.file.allow=never", "core.excludesFile=/dev/null", "status.showUntrackedFiles=all"} {
		if !strings.Contains(strings.Join(cmd.Args, " "), option) {
			t.Fatal("missing safety override", option)
		}
	}
	ignore := filepath.Join(t.TempDir(), "ignore")
	if err := os.WriteFile(ignore, []byte("hidden.txt\n"), 0600); err != nil {
		t.Fatal(err)
	}
	testutil.Git(t, root, "config", "core.excludesFile", ignore)
	testutil.Git(t, root, "config", "status.showUntrackedFiles", "no")
	if err := os.WriteFile(filepath.Join(root, "hidden.txt"), []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	status, err := Run(context.Background(), root, "status", "--porcelain")
	if err != nil || !strings.Contains(status, "hidden.txt") {
		t.Fatal("untracked path hidden", err)
	}
}

func TestConfigOriginsAndSafetyOverrides(t *testing.T) {
	keys, worktree := configKeys("file:/etc/gitconfig\x00filter.system.clean\nunsafe\x00file:config\x00extensions.worktreeConfig\ntrue\x00")
	if !worktree || !strings.Contains(strings.Join(neutralFilters(keys), " "), "filter.system.clean=cat") {
		t.Fatal("system scope or worktree switch missing")
	}
	if len(neutralFilters("include.path\x00")) != 0 {
		t.Fatal("include.path must not become a safety override")
	}
}

func TestLocalCloneRequiresExplicitFlag(t *testing.T) {
	root := testutil.Repository(t)
	dir := t.TempDir()
	ctx := context.Background()
	if err := Clone(ctx, dir, "file://"+root, filepath.Join(dir, "denied"), false); err == nil {
		t.Fatal("local transport allowed implicitly")
	}
	if err := Clone(ctx, dir, "file://"+root, filepath.Join(dir, "allowed"), true); err != nil {
		t.Fatal("explicit local clone failed", err)
	}
}
