package workspace

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentsflow/harness/internal/gitrepo"
)

var taskIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`)

// Ensure creates a sibling worktree from HEAD or reuses the registered task
// branch, including uncommitted work. It never checks out in the primary tree.
func Ensure(ctx context.Context, repository, taskID string) (string, error) {
	if !taskIDPattern.MatchString(taskID) {
		return "", errors.New("invalid task id")
	}
	root, err := gitrepo.Root(ctx, repository)
	if err != nil {
		return "", err
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return "", errors.New("primary repository path is not canonical")
	}
	branch := "task/" + taskID
	listing, err := gitrepo.Run(ctx, root, "worktree", "list", "--porcelain", "-z")
	if err != nil {
		return "", err
	}
	if path := registered(listing, branch); path != "" {
		return reuse(ctx, root, path, branch)
	}
	path := filepath.Join(filepath.Dir(root), filepath.Base(root)+"-task-"+taskID)
	if _, err := os.Lstat(path); err == nil || !os.IsNotExist(err) {
		return "", errors.New("task worktree path already exists but is not registered")
	}
	args := []string{"worktree", "add"}
	if _, err := gitrepo.Run(ctx, root, "show-ref", "--verify", "--quiet", "refs/heads/"+branch); err != nil {
		args = append(args, "-b", branch, path, "HEAD")
	} else {
		args = append(args, path, branch)
	}
	if _, err := gitrepo.Run(ctx, root, args...); err != nil {
		// Another caller may have created the same worktree in the meantime.
		listing, _ := gitrepo.Run(ctx, root, "worktree", "list", "--porcelain", "-z")
		if found := registered(listing, branch); found != "" {
			return reuse(ctx, root, found, branch)
		}
		return "", err
	}
	return path, nil
}

func registered(listing, branch string) string {
	var path string
	for _, field := range strings.Split(listing, "\x00") {
		if strings.HasPrefix(field, "worktree ") {
			path = strings.TrimPrefix(field, "worktree ")
		}
		if field == "branch refs/heads/"+branch {
			return path
		}
	}
	return ""
}

func reuse(ctx context.Context, root, path, branch string) (string, error) {
	path, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() {
		return "", errors.New("registered task worktree is missing or not a directory")
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("registered task worktree cannot be a symlink")
	}
	actualPath, err := filepath.EvalSymlinks(path)
	if err != nil || actualPath != filepath.Clean(path) {
		return "", errors.New("registered task worktree path is not canonical")
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return "", errors.New("primary repository path is not canonical")
	}
	if filepath.Dir(actualPath) != filepath.Dir(root) || actualPath == root {
		return "", errors.New("task worktree must be a canonical sibling of the primary working tree")
	}
	rel, err := filepath.Rel(root, actualPath)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) == false {
		return "", errors.New("task worktree must be outside the primary working tree")
	}
	actual, err := gitrepo.Run(ctx, path, "symbolic-ref", "--short", "HEAD")
	if err != nil || actual != branch {
		return "", errors.New("registered worktree has an unexpected branch")
	}
	return path, nil
}
