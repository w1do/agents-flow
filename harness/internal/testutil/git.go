// Package testutil provides isolated repositories for integration tests.
package testutil

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func Git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	cmd.Env = append(os.Environ(), "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_NO_LAZY_FETCH=1")
	data, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, data)
	}
	return strings.TrimSpace(string(data))
}

func Repository(t *testing.T) string {
	t.Helper()
	root := filepath.Join(t.TempDir(), "repository")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	Git(t, root, "init", "-b", "main")
	Git(t, root, "config", "user.email", "harness@example.invalid")
	Git(t, root, "config", "user.name", "Harness test")
	Write(t, filepath.Join(root, "tracked.txt"), "original\n")
	Git(t, root, "add", "tracked.txt")
	Git(t, root, "commit", "-m", "initial")
	Git(t, root, "remote", "add", "origin", "https://example.invalid/project.git")
	return root
}

func Write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}

func Read(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}
