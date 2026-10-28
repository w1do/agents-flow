package gitrepo

import (
	"context"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestSpecificTransportOptInsAreOverridden(t *testing.T) {
	root := testutil.Repository(t)
	for protocol, remote := range map[string]string{
		"http": "http://127.0.0.1:bad/repo", "ssh": "ssh://fixture.invalid/repo",
		"ftps": "ftps://127.0.0.1:bad/repo", "unknown": "unknown://fixture.invalid/repo",
		"sftp": "sftp://fixture.invalid/repo", "rsync": "rsync::fixture.invalid/repo",
		"ext": "ext::false",
	} {
		t.Run(protocol, func(t *testing.T) {
			testutil.Git(t, root, "config", "protocol."+protocol+".allow", "always")
			options := []string{"-c", "protocol." + protocol + ".allow=always"}
			testutil.Git(t, root, "config", "protocol.allow", "always")
			for _, discover := range []bool{false, true} {
				for _, allowLocal := range []bool{false, true} {
					cmd := configuredCommand(context.Background(), root, options, discover, allowLocal,
						"ls-remote", remote)
					output, err := cmd.CombinedOutput()
					if err == nil || !strings.Contains(string(output), "transport '"+protocol+"' not allowed") {
						t.Fatalf("transport protection failed: %v %s", err, output)
					}
				}
			}
		})
	}
}

func TestLocalCloneOverridesFinalFileDenyOnly(t *testing.T) {
	root := testutil.Repository(t)
	dir := t.TempDir()
	ctx := context.Background()
	options := []string{"-c", "protocol.file.allow=always"}
	cmd := configuredCommand(ctx, dir, options, false, true, "clone")
	args := strings.Join(cmd.Args, " ")
	if strings.LastIndex(args, "protocol.file.allow=always") < strings.LastIndex(args, "protocol.file.allow=never") {
		t.Fatal("local clone opt-in must follow the final deny")
	}
	if err := Clone(ctx, dir, "file://"+root, filepath.Join(dir, "denied"), false); err == nil {
		t.Fatal("local clone allowed without opt-in")
	}
	if err := Clone(ctx, dir, "file://"+root, filepath.Join(dir, "allowed"), true); err != nil {
		t.Fatal("explicit local clone failed", err)
	}
}
