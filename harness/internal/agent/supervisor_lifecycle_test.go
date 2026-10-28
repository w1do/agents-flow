package agent

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestAbandonedHarnessHelper(t *testing.T) {
	if len(os.Args) < 3 || os.Args[len(os.Args)-2] != "abandoned-harness" {
		return
	}
	dir := os.Args[len(os.Args)-1]
	_ = runProcess(context.Background(), []string{"sh", "-c", `sleep 60 & echo $! > orphan.pid; printf '%s\n' '{"type":"progress"}'; wait`},
		runnerInput{Worktree: dir}, map[string]string{"GORACE": "atexit_sleep_ms=0"}, func(runnerEvent) error { os.Exit(0); return nil })
	os.Exit(20)
}

func TestSupervisorCleansAfterHarnessAbruptExit(t *testing.T) {
	dir := t.TempDir()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(exe, "-test.run=^TestAbandonedHarnessHelper$", "--", "abandoned-harness", dir)
	cmd.Env = append(os.Environ(), "GORACE=atexit_sleep_ms=0")
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "orphan.pid"))
	if err != nil {
		t.Fatal(err)
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.Kill(pid, syscall.SIGKILL)
	for deadline := time.Now().Add(3 * time.Second); time.Now().Before(deadline); {
		if errors.Is(syscall.Kill(pid, 0), syscall.ESRCH) {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("descendant outlived abandoned harness and supervisor")
}

func TestParallelSupervisorsDoNotReapEachOthersChildren(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	started := make(chan struct{})
	longDone := make(chan error, 1)
	dir := t.TempDir()
	go func() {
		longDone <- runProcess(ctx, []string{"sh", "-c", `printf '%s\n' '{"type":"progress"}'; sleep 60`},
			runnerInput{Worktree: dir}, nil, func(runnerEvent) error { close(started); return nil })
	}()
	<-started
	shortCtx, stop := context.WithTimeout(context.Background(), 3*time.Second)
	defer stop()
	shortDone := make(chan error, 1)
	go func() {
		shortDone <- runProcess(shortCtx, []string{"sh", "-c", `sleep .1; printf '%s\n' '{"type":"result"}'`},
			runnerInput{Worktree: dir}, nil, func(runnerEvent) error { return nil })
	}()
	cancel()
	if err := <-longDone; !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if err := <-shortDone; err != nil {
		t.Fatal("other runner was reaped or killed", err)
	}
}
