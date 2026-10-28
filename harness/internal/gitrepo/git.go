package gitrepo

import (
	"context"
	"errors"
	"strings"
)

// Run only exposes stdout on success; Git diagnostics may include remote secrets.
func Run(ctx context.Context, dir string, args ...string) (string, error) {
	options, err := filterOptions(ctx, dir)
	if err != nil {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return "", errors.New("git config failed")
	}
	data, err := command(ctx, dir, options, args...).Output()
	if err != nil {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return "", errors.New("git " + args[0] + " failed")
	}
	return strings.TrimRight(string(data), "\r\n"), nil
}

func Root(ctx context.Context, dir string) (string, error) {
	root, err := Run(ctx, dir, "rev-parse", "--show-toplevel")
	if err != nil {
		if ctx.Err() != nil {
			return "", context.Cause(ctx)
		}
		return "", errors.New("run harness inside a Git working tree")
	}
	return root, nil
}

func Origin(ctx context.Context, root string) (string, error) {
	remotes, err := Run(ctx, root, "remote")
	if err != nil {
		return "", err
	}
	for _, remote := range strings.Fields(remotes) {
		if remote == "origin" {
			return Run(ctx, root, "remote", "get-url", "origin")
		}
	}
	return "", nil
}
