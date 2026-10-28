package skills

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/testutil"
)

type source struct {
	files []api.Skill
	calls int
	err   error
}

func (s *source) Skills(context.Context, string) ([]api.Skill, error) {
	s.calls++
	return s.files, s.err
}

func TestSyncLifecycleAndActiveTask(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "skills")
	remote := &source{files: []api.Skill{{Filename: "test--one.md", Version: 1, Content: "original"}}}
	syncer := New(dir, "agent", remote)
	ctx := context.Background()
	if err := syncer.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "test--one.md")
	before, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := syncer.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	after, err := os.Stat(path)
	if err != nil || !os.SameFile(before, after) {
		t.Fatal("unchanged skill was replaced", err)
	}
	syncer.SetActive(true)
	remote.files = []api.Skill{{Filename: "test--one.md", Version: 2, Content: "updated"},
		{Filename: "test--two.md", Version: 1, Content: "new"}}
	calls := remote.calls
	if err := syncer.Sync(ctx); !errors.Is(err, ErrActive) || remote.calls != calls {
		t.Fatal("sync attempted during active task")
	}
	if testutil.Read(t, path) != "original" {
		t.Fatal("active task skills changed")
	}
	syncer.SetActive(false)
	if err := syncer.Sync(ctx); err != nil || testutil.Read(t, path) != "updated" {
		t.Fatal("skill not updated", err)
	}
	if testutil.Read(t, filepath.Join(dir, "test--two.md")) != "new" {
		t.Fatal("new skill not downloaded")
	}
	remote.err = errors.New("offline")
	if err := syncer.Sync(ctx); err == nil || testutil.Read(t, path) != "updated" {
		t.Fatal("network failure changed local skills")
	}
	remote.err, remote.files = nil, nil
	if err := syncer.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 0 {
		t.Fatal("removed assignments remain on disk", err)
	}
}

func TestRejectUnsafeSkillsBeforeChangingFiles(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test--original.md")
	testutil.Write(t, path, "keep")
	for _, name := range []string{"../escape.md", "/tmp/escape.md", "invalid.md", "test--bad\\path.md"} {
		if err := Apply(dir, []api.Skill{{Filename: name, Content: "unsafe"}}); err == nil {
			t.Error("unsafe filename accepted", name)
		}
		if testutil.Read(t, path) != "keep" {
			t.Fatal("invalid input changed existing files")
		}
	}
	if err := os.Symlink(path, filepath.Join(dir, "test--link.md")); err != nil {
		t.Fatal(err)
	}
	if err := Apply(dir, []api.Skill{{Name: "test--link.md", Content: "overwrite"}}); err == nil {
		t.Fatal("symlink accepted")
	}
	if testutil.Read(t, path) != "keep" {
		t.Fatal("symlink target changed")
	}
}

func TestRejectSymlinkInSkillsPathComponents(t *testing.T) {
	project := t.TempDir()
	outside := filepath.Join(t.TempDir(), "workflow")
	if err := os.Mkdir(outside, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(project, "workflow")); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(project, "workflow", "skills")
	if err := Apply(dir, []api.Skill{{Filename: "development--one.md", Content: "safe"}}); err == nil {
		t.Fatal("symlinked path component accepted")
	}
	if _, err := os.Stat(filepath.Join(outside, "skills")); !os.IsNotExist(err) {
		t.Fatal("write escaped through symlink")
	}
}

func TestPinnedSkillsRootSurvivesDirectoryReplacement(t *testing.T) {
	project := t.TempDir()
	dir := filepath.Join(project, "workflow", "skills")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	moved := filepath.Join(project, "skills-original")
	if err := os.Rename(dir, moved); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	if err := os.Symlink(outside, dir); err != nil {
		t.Fatal(err)
	}
	if err := applyFiles(root, map[string][]byte{"test--one.md": []byte("safe")}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(outside, "test--one.md")); !os.IsNotExist(err) {
		t.Fatal("directory replacement redirected write outside project")
	}
	if got, err := os.ReadFile(filepath.Join(moved, "test--one.md")); err != nil || string(got) != "safe" {
		t.Fatalf("pinned directory not updated: %q, %v", got, err)
	}
}
