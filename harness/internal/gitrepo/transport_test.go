package gitrepo

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestMissingPromisorBlobCannotExecuteSSH(t *testing.T) {
	root := testutil.Repository(t)
	blob := testutil.Git(t, root, "rev-parse", "HEAD:tracked.txt")
	if err := os.Remove(filepath.Join(root, ".git", "objects", blob[:2], blob[2:])); err != nil {
		t.Fatal(err)
	}
	testutil.Git(t, root, "config", "remote.origin.promisor", "true")
	testutil.Git(t, root, "config", "remote.origin.url", "ssh://fixture.invalid/repo")
	testutil.Git(t, root, "config", "core.sshCommand", "touch transport-ran; false")
	if _, err := Run(context.Background(), root, "cat-file", "blob", blob); err == nil {
		t.Fatal("missing blob unexpectedly available")
	}
	if _, err := os.Stat(filepath.Join(root, "transport-ran")); !os.IsNotExist(err) {
		t.Fatal("transport executed")
	}
}

func TestExplicitExtAllowCannotExecuteTransport(t *testing.T) {
	root := testutil.Repository(t)
	testutil.Git(t, root, "config", "protocol.ext.allow", "always")
	ctx := context.Background()
	remote := "ext::sh -c touch% transport-ran"
	if _, err := Run(ctx, root, "ls-remote", remote); err == nil {
		t.Fatal("ext transport unexpectedly allowed")
	}
	for _, allowLocal := range []bool{false, true} {
		if err := Clone(ctx, root, remote, filepath.Join(t.TempDir(), "clone"), allowLocal); err == nil {
			t.Fatal("clone unexpectedly allowed ext transport")
		}
	}
	if _, err := os.Stat(filepath.Join(root, "transport-ran")); !os.IsNotExist(err) {
		t.Fatal("ext transport executed")
	}
}
