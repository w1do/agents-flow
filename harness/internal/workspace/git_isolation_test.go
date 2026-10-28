package workspace

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestCheckoutDisablesHooksAndFilters(t *testing.T) {
	for _, process := range []bool{false, true} {
		t.Run(map[bool]string{false: "smudge", true: "process"}[process], func(t *testing.T) {
			root := testutil.Repository(t)
			want := []byte("literal\r\nbytes\r\n")
			testutil.Write(t, filepath.Join(root, ".gitattributes"), "*.txt filter=audit -text\n")
			testutil.Write(t, filepath.Join(root, "tracked.txt"), string(want))
			testutil.Git(t, root, "add", ".gitattributes", "tracked.txt")
			testutil.Git(t, root, "commit", "-m", "fixture")
			hook := filepath.Join(root, ".git", "hooks", "post-checkout")
			testutil.Write(t, hook, "#!/bin/sh\ntouch hook-ran\n")
			if err := os.Chmod(hook, 0755); err != nil {
				t.Fatal(err)
			}
			testutil.Git(t, root, "config", "filter.audit.smudge", "touch filter-ran; printf altered")
			if process {
				testutil.Git(t, root, "config", "filter.audit.process", "touch filter-ran; exit 1")
				testutil.Git(t, root, "config", "filter.audit.required", "true")
			}
			path, err := Ensure(context.Background(), root, "isolation")
			if err != nil {
				t.Fatal(err)
			}
			got, err := os.ReadFile(filepath.Join(path, "tracked.txt"))
			if err != nil || !bytes.Equal(got, want) {
				t.Fatal("checkout changed file bytes", err)
			}
			for _, name := range []string{"hook-ran", "filter-ran"} {
				if _, err := os.Stat(filepath.Join(path, name)); !os.IsNotExist(err) {
					t.Fatal("repository program executed", name, err)
				}
			}
		})
	}
}
