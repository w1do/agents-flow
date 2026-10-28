//go:build linux

package procguard

import (
	"os"
	"os/exec"
	"syscall"
	"testing"
	"time"
)

func TestSupervisorCleanupHelper(t *testing.T) {
	mode := os.Getenv("PROCGUARD_TEST_MODE")
	if mode == "" {
		return
	}
	args := []string{"/bin/sh", "-c", "sleep 60"}
	if mode == "stream" {
		args[2] = "while :; do true & wait; done"
	}
	if mode == "eperm" {
		supervisorCleanupTimeout = 150 * time.Millisecond
		supervisorKill = func(int, syscall.Signal) error { return syscall.EPERM }
	}
	code := supervise(args)
	if mode == "eperm" {
		// Remove the deliberately unkillable test child after exercising the
		// supervisor deadline, so the test cannot leave a process behind.
		if children, err := ownedChildren(); err == nil {
			for _, pid := range children {
				_ = syscall.Kill(pid, syscall.SIGKILL)
			}
		}
	}
	os.Exit(code)
}

func TestSupervisorBoundsCleanupWhenKillReturnsEPERM(t *testing.T) {
	assertSupervisorStops(t, "eperm", 2*time.Second)
}

func TestSupervisorSignalDuringContinuousReapingStopsPromptly(t *testing.T) {
	assertSupervisorStops(t, "stream", 2*time.Second)
}

func assertSupervisorStops(t *testing.T, mode string, limit time.Duration) {
	t.Helper()
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(exe, "-test.run=^TestSupervisorCleanupHelper$")
	cmd.ExtraFiles = []*os.File{reader}
	cmd.Env = append(os.Environ(), "PROCGUARD_TEST_MODE="+mode)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	reader.Close()
	defer writer.Close()
	time.Sleep(40 * time.Millisecond)
	started := time.Now()
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if time.Since(started) > limit {
			t.Fatalf("supervisor exceeded shutdown bound: %s", time.Since(started))
		}
		// The runner is killed during cleanup, so a signal-derived nonzero
		// exit status is expected; completion within the bound is the contract.
		_ = err
	case <-time.After(limit):
		_ = cmd.Process.Kill()
		t.Fatal("supervisor did not stop within the cleanup bound")
	}
}
