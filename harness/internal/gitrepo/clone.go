package gitrepo

import (
	"context"
	"errors"
)

// Clone is the only path permitting local transport, with explicit caller opt-in.
// --no-checkout prevents untrusted filters/hooks in the newly cloned repository.
func Clone(ctx context.Context, dir, source, destination string, allowLocal bool) error {
	options, err := filterOptions(ctx, dir)
	if err != nil {
		return errors.New("git config failed")
	}
	cmd := configuredCommand(ctx, dir, options, false, allowLocal,
		"clone", "--no-checkout", "--", source, destination)
	if _, err := cmd.Output(); err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errors.New("git clone failed")
	}
	return nil
}
