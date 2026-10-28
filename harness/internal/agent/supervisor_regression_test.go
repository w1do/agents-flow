package agent

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestImmediateDoubleForkSetsidIsReaped(t *testing.T) {
	for range 4 {
		dir := t.TempDir()
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		err := runProcess(ctx, []string{"sh", "-c", `setsid sh -c 'sleep 60 & echo $! > escaped.pid; exit 0' >/dev/null 2>&1 & wait`}, runnerInput{Worktree: dir}, nil, func(runnerEvent) error { return nil })
		cancel()
		data, readErr := os.ReadFile(filepath.Join(dir, "escaped.pid"))
		if readErr != nil {
			t.Fatal(readErr)
		}
		pid, parseErr := strconv.Atoi(strings.TrimSpace(string(data)))
		if parseErr != nil {
			t.Fatal(parseErr)
		}
		alive := syscall.Kill(pid, 0)
		if !errors.Is(alive, syscall.ESRCH) {
			_ = syscall.Kill(pid, syscall.SIGKILL)
		}
		if err != nil || !errors.Is(alive, syscall.ESRCH) {
			t.Fatalf("detached descendant was not reaped: err=%v live=%v", err, alive)
		}
	}
}
