package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"

	"agentsflow/harness/internal/procguard"
)

var (
	errRunnerFailed   = errors.New("runner failed; checkpoint preserved")
	errRunnerProtocol = errors.New("invalid runner event stream")
)

func runProcess(ctx context.Context, command []string, input runnerInput, configuredEnv map[string]string, consume func(runnerEvent) error) error {
	if ctx.Err() != nil {
		return context.Cause(ctx)
	}
	data, err := json.Marshal(input)
	if err != nil {
		return errors.New("cannot encode runner input")
	}
	processCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	cmd, cleanup, err := procguard.Command(processCtx, command)
	if err != nil {
		return errRunnerFailed
	}
	defer cleanup()
	cmd.Dir = input.Worktree
	cmd.Stdin = bytes.NewReader(append(data, '\n'))
	stderr, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		return errRunnerFailed
	}
	defer stderr.Close()
	cmd.Stderr = stderr
	cmd.Env = runnerEnvironment(configuredEnv)
	stdout, writer, err := os.Pipe()
	if err != nil {
		return errRunnerFailed
	}
	defer stdout.Close()
	stopClose := context.AfterFunc(processCtx, func() { _ = stdout.Close() })
	defer stopClose()
	cmd.Stdout = writer
	if err := cmd.Start(); err != nil {
		writer.Close()
		if ctx.Err() != nil {
			return context.Cause(ctx)
		}
		return errRunnerFailed
	}
	_ = writer.Close()
	waited := make(chan error, 1)
	go func() { waited <- cmd.Wait() }()
	stream := readEvents(processCtx, stdout)
	var streamErr error
	for item := range stream {
		if ctx.Err() != nil {
			streamErr = context.Cause(ctx)
			break
		}
		if item.err != nil {
			streamErr = item.err
			break
		}
		if err := consume(item.event); err != nil {
			streamErr = err
			break
		}
	}
	if streamErr != nil {
		cancel()
		_ = stdout.Close()
	}
	// No close on ordinary process exit: a slow API consumer must still see
	// every queued event and every remaining byte through a genuine EOF.
	for range stream {
	}
	waitErr := <-waited
	if ctx.Err() != nil {
		return context.Cause(ctx)
	}
	if streamErr != nil {
		return streamErr
	}
	if waitErr != nil {
		return errRunnerFailed
	}
	return nil
}
