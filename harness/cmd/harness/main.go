package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"agentsflow/harness/internal/cli"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	dir, err := os.Getwd()
	if err == nil {
		err = cli.Execute(ctx, os.Args[1:], cli.Environment{
			Directory: dir, Input: os.Stdin, Output: os.Stdout, Getenv: os.Getenv,
		})
	}
	if err != nil && !errors.Is(err, context.Canceled) {
		fmt.Fprintln(os.Stderr, "harness:", err)
		os.Exit(1)
	}
}
