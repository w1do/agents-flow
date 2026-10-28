package workspace

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestCreateReuseAndMainTreeUnchanged(t *testing.T) {
	root := testutil.Repository(t)
	testutil.Write(t, filepath.Join(root, "tracked.txt"), "uncommitted main changes\n")
	testutil.Write(t, filepath.Join(root, "untracked.txt"), "main only")
	before := testutil.Git(t, root, "status", "--porcelain", "--untracked-files=all")
	head := testutil.Git(t, root, "rev-parse", "HEAD")
	ctx := context.Background()
	path, err := Ensure(ctx, root, "task-123")
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Dir(path) != filepath.Dir(root) || path == root {
		t.Fatal("worktree must be a separate sibling")
	}
	if testutil.Git(t, path, "branch", "--show-current") != "task/task-123" {
		t.Fatal("unexpected task branch")
	}
	if testutil.Read(t, filepath.Join(path, "tracked.txt")) != "original\n" {
		t.Fatal("worktree copied uncommitted main changes")
	}
	testutil.Write(t, filepath.Join(path, "tracked.txt"), "task progress\n")
	testutil.Write(t, filepath.Join(path, "checkpoint.txt"), "saved")
	reused, err := Ensure(ctx, root, "task-123")
	if err != nil || reused != path || testutil.Read(t, filepath.Join(path, "tracked.txt")) != "task progress\n" {
		t.Fatal("existing worktree was not reused intact", err)
	}
	if testutil.Git(t, root, "branch", "--show-current") != "main" || testutil.Git(t, root, "rev-parse", "HEAD") != head {
		t.Fatal("main branch changed")
	}
	if testutil.Read(t, filepath.Join(root, "tracked.txt")) != "uncommitted main changes\n" ||
		testutil.Git(t, root, "status", "--porcelain", "--untracked-files=all") != before {
		t.Fatal("main working copy changed")
	}
}

func TestReuseExistingBranch(t *testing.T) {
	root := testutil.Repository(t)
	testutil.Git(t, root, "branch", "task/existing")
	path, err := Ensure(context.Background(), root, "existing")
	if err != nil || testutil.Git(t, path, "branch", "--show-current") != "task/existing" {
		t.Fatal("existing branch could not be reused", err)
	}
	// Registered worktrees with custom paths are also reused after a restart.
	custom := filepath.Join(filepath.Dir(root), "custom path")
	testutil.Git(t, root, "worktree", "add", "-b", "task/custom", custom)
	path, err = Ensure(context.Background(), root, "custom")
	if err != nil || path != custom {
		t.Fatal("registered custom path not reused", err)
	}
}

func TestRejectUnsafeTaskAndPathCollision(t *testing.T) {
	root := testutil.Repository(t)
	for _, id := range []string{"", "../escape", "a/b", "--force", "a\nb"} {
		if _, err := Ensure(context.Background(), root, id); err == nil {
			t.Error("unsafe task id accepted")
		}
	}
	path := filepath.Join(filepath.Dir(root), filepath.Base(root)+"-task-collision")
	if err := os.Mkdir(path, 0755); err != nil {
		t.Fatal(err)
	}
	testutil.Write(t, filepath.Join(path, "keep"), "keep")
	if _, err := Ensure(context.Background(), root, "collision"); err == nil {
		t.Fatal("unregistered directory accepted")
	}
	if testutil.Read(t, filepath.Join(path, "keep")) != "keep" {
		t.Fatal("existing path modified")
	}
	testutil.Git(t, root, "checkout", "-b", "task/primary")
	if _, err := Ensure(context.Background(), root, "primary"); err == nil {
		t.Fatal("primary copy accepted as task workspace")
	}
}

func TestRejectRegisteredNestedWorktree(t *testing.T) {
	root := testutil.Repository(t)
	nested := filepath.Join(root, "nested-worktree")
	testutil.Git(t, root, "worktree", "add", "-b", "task/nested", nested, "HEAD")
	if _, err := Ensure(context.Background(), root, "nested"); err == nil {
		t.Fatal("worktree nested in primary repository accepted")
	}
}
