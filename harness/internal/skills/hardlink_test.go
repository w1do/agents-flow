package skills

import (
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/testutil"
)

func TestUpdatingHardlinkedSkillDoesNotModifyExternalInode(t *testing.T) {
	base := t.TempDir()
	dir := filepath.Join(base, "project", "workflow", "skills")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	external := filepath.Join(base, "external")
	testutil.Write(t, external, "external content")
	before, err := os.Stat(external)
	if err != nil {
		t.Fatal(err)
	}
	skill := filepath.Join(dir, "test--linked.md")
	if err := os.Link(external, skill); err != nil {
		t.Fatal(err)
	}
	if err := Apply(dir, []api.Skill{{Filename: "test--linked.md", Content: "new skill"}}); err != nil {
		t.Fatal(err)
	}
	after, err := os.Stat(external)
	if err != nil || after.Mode() != before.Mode() || testutil.Read(t, external) != "external content" {
		t.Fatal("skill update modified the external hardlink target or its permissions", err)
	}
	saved, err := os.Stat(skill)
	if err != nil || os.SameFile(before, saved) || testutil.Read(t, skill) != "new skill" {
		t.Fatal("skill entry was not atomically replaced", err)
	}
}
