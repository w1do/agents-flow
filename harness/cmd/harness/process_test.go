package main

import (
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

func checkStopped(t *testing.T, dir, file string) {
	t.Helper()
	pid, err := strconv.Atoi(strings.TrimSpace(testutil.Read(t, filepath.Join(dir, file))))
	if err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(time.Second); time.Now().Before(deadline); {
		if errors.Is(syscall.Kill(pid, 0), syscall.ESRCH) {
			return
		}
		data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
		if err != nil || strings.Contains(string(data), ") Z ") {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("runner process survived signal")
}
