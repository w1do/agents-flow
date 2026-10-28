package gitrepo

import (
	"context"
	"errors"
	"testing"
)

func TestRootPreservesCancellationCause(t *testing.T) {
	ctx, cancel := context.WithCancelCause(context.Background())
	want := errors.New("lease lost")
	cancel(want)
	if _, err := Root(ctx, t.TempDir()); !errors.Is(err, want) {
		t.Fatal("cancellation cause lost", err)
	}
}
