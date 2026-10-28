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

	"agentsflow/harness/internal/testutil"
)

func assertDescendantStopped(t *testing.T, worktree string) {
	t.Helper()
	pid, err := strconv.Atoi(testutil.Read(t, filepath.Join(worktree, "descendant.pid")))
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if errors.Is(syscall.Kill(pid, 0), syscall.ESRCH) {
			return
		}
		data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
		if err != nil || strings.Contains(string(data), ") Z ") {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("runner descendant survived shutdown")
}

func TestNormalRunnerExitKillsBackgroundDescendant(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, root := fixture(t, s, "descendant")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	assertDescendantStopped(t, filepath.Join(filepath.Dir(root), "repository-task-task"))
}

func TestJournalLocksOutSecondProcess(t *testing.T) {
	s := newFlowServer(t, "pending-plan")
	e, _ := fixture(t, s, "normal")
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.planPolls > 0 })
	other, err := New(e.cfg, "agent-secret", e.options)
	if err != nil {
		t.Fatal(err)
	}
	if err := other.Run(context.Background()); err == nil || !strings.Contains(err.Error(), "already active") {
		t.Fatal(err)
	}
	cancel()
	<-done
}

func TestCancellationKillsSetsidDescendantAndUnblocksPipe(t *testing.T) {
	root := t.TempDir()
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	started := time.Now()
	err := runProcess(ctx, []string{"sh", "-c", "setsid sleep 60 & wait"}, runnerInput{Worktree: root}, nil, func(runnerEvent) error { return nil })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected context deadline, got %v", err)
	}
	if time.Since(started) > 3*time.Second {
		t.Fatal("runner cancellation hung")
	}
}

func TestImmediateSetsidChildDoesNotHoldRunnerPipe(t *testing.T) {
	root := t.TempDir()
	started := time.Now()
	err := runProcess(context.Background(), []string{"sh", "-c", "setsid sleep 60 & echo $! > child.pid; exit 0"}, runnerInput{Worktree: root}, nil, func(runnerEvent) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(started) > 3*time.Second {
		t.Fatal("runner waited for detached child's stdout")
	}
	pid, err := strconv.Atoi(strings.TrimSpace(testutil.Read(t, filepath.Join(root, "child.pid"))))
	if err != nil {
		t.Fatal(err)
	}
	if err := syscall.Kill(pid, 0); !errors.Is(err, syscall.ESRCH) {
		t.Fatalf("detached process %d survived: %v", pid, err)
	}
}

func TestProcStatParsesCommandWithSpacesAndParent(t *testing.T) {
	pid, parent, start, err := parseProcStat("42 (command with (nested) spaces) S 7 " + strings.Repeat("0 ", 17) + "987654 0")
	if err != nil || pid != 42 || parent != 7 || start != 987654 {
		t.Fatalf("parsed stat = %d %d %d, %v", pid, parent, start, err)
	}
}

func TestSavedPIDIdentityMismatchIsNotSignalled(t *testing.T) {
	pid := os.Getpid()
	current, err := processStartTime(pid)
	if err != nil {
		t.Fatal(err)
	}
	if killPIDIfSame(pid, current+1) == nil {
		t.Fatal("mismatched PID identity was signalled")
	}
	if err := syscall.Kill(pid, 0); err != nil {
		t.Fatalf("current process was affected: %v", err)
	}
}

func TestRunnerEnvironmentUsesWhitelistAndExplicitOverrides(t *testing.T) {
	t.Setenv("PATH", "/safe/bin")
	t.Setenv("HOME", "/safe/home")
	t.Setenv("GIT_ASKPASS", "credential-helper")
	t.Setenv("SERVICE_TOKEN", "private")
	env := runnerEnvironment(map[string]string{"CUSTOM_SETTING": "enabled", "SERVICE_TOKEN": "explicit"})
	joined := strings.Join(env, "\n")
	for _, want := range []string{"PATH=/safe/bin", "HOME=/safe/home", "CUSTOM_SETTING=enabled", "SERVICE_TOKEN=explicit"} {
		if !strings.Contains(joined, want) {
			t.Fatal("runner environment omitted", want)
		}
	}
	for _, forbidden := range []string{"GIT_ASKPASS", "credential-helper", "SERVICE_TOKEN=private"} {
		if strings.Contains(joined, forbidden) {
			t.Fatal("runner inherited unapproved environment", forbidden)
		}
	}
}
