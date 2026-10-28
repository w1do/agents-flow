//go:build !linux

package procguard

import (
	"context"
	"errors"
	"os/exec"
)

const Supported = false

func Command(context.Context, []string) (*exec.Cmd, func(), error) {
	return nil, nil, errors.New("runner supervision requires Linux subreaper support")
}
