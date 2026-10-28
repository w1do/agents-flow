//go:build linux

// Package procguard gives each runner a private subreaper supervisor.
package procguard

import (
	"context"
	"os"
	"os/exec"
	"syscall"
)

const supervisorFlag = "--_harness-runner-supervisor"
const Supported = true

func init() {
	if len(os.Args) > 2 && os.Args[1] == supervisorFlag {
		os.Exit(supervise(os.Args[2:]))
	}
}

func Command(ctx context.Context, args []string) (*exec.Cmd, func(), error) {
	exe, err := os.Executable()
	if err != nil {
		return nil, nil, err
	}
	reader, writer, err := os.Pipe()
	if err != nil {
		return nil, nil, err
	}
	cleanup := func() { _ = reader.Close(); _ = writer.Close() }
	cmd := exec.CommandContext(ctx, exe, append([]string{supervisorFlag}, args...)...)
	cmd.ExtraFiles = []*os.File{reader}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	// SIGTERM reaches the supervisor only; it kills and reaps all descendants
	// before exiting. Killing its process group would destroy the subreaper first.
	cmd.Cancel = func() error { return cmd.Process.Signal(syscall.SIGTERM) }
	return cmd, cleanup, nil
}
