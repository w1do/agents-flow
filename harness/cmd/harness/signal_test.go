package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/testutil"
)

func TestMainProcessHelper(t *testing.T) {
	for _, arg := range os.Args {
		if arg == "harness-process" {
			os.Args = []string{"harness", "run"}
			main()
			os.Exit(0)
		}
	}
}

func TestSignalsStopRunnerAndHeartbeat(t *testing.T) {
	for _, signal := range []syscall.Signal{syscall.SIGINT, syscall.SIGTERM} {
		t.Run(signal.String(), func(t *testing.T) {
			root := testutil.Repository(t)
			var heartbeat atomic.Int32
			var checkpoint atomic.Bool
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.HasSuffix(r.URL.Path, "/skills/sync"):
					_, _ = w.Write([]byte(`{"skills":[]}`))
				case strings.HasSuffix(r.URL.Path, "/leases/claim"):
					_ = json.NewEncoder(w).Encode(api.ClaimResponse{Task: api.Task{ID: "task"}, LeaseID: "lease", LeaseExpiresAt: time.Now().Add(time.Minute)})
				case strings.HasSuffix(r.URL.Path, "/heartbeat"):
					heartbeat.Add(1)
					_, _ = w.Write([]byte(`{"status":"busy"}`))
				case strings.HasSuffix(r.URL.Path, "/execution-state"):
					_ = json.NewEncoder(w).Encode(api.ExecutionState{TaskID: "task", LeaseID: "lease", Status: "planning"})
				case strings.HasSuffix(r.URL.Path, "/events"):
					body, _ := io.ReadAll(r.Body)
					if bytes.Contains(body, []byte("running")) {
						checkpoint.Store(true)
					}
					_, _ = w.Write([]byte(`{}`))
				default:
					t.Error("unexpected report after signal", r.URL.Path)
					w.WriteHeader(409)
				}
			}))
			defer server.Close()
			script := filepath.Join(t.TempDir(), "runner.sh")
			testutil.Write(t, script, "#!/bin/sh\nread -r input\nsleep 300 &\necho $! > runner-child.pid\necho $$ > runner.pid\nprintf '%s\\n' '{\"type\":\"progress\",\"checkpoint\":{\"step\":\"running\"}}'\nwait\n")
			if err := os.Mkdir(filepath.Join(root, "workflow"), 0755); err != nil {
				t.Fatal(err)
			}
			cfg := config.Config{ServerURL: server.URL, ProjectID: "project", AgentID: "agent", WorkspacePath: root,
				GitRemote: "origin", PollIntervalSeconds: 1, LeaseTTLSeconds: 1, Runner: config.Runner{Command: []string{"/bin/sh", script}}}
			if err := config.Write(filepath.Join(root, "workflow"), cfg, "secret-agent-token"); err != nil {
				t.Fatal(err)
			}
			exe, _ := os.Executable()
			cmd := exec.Command(exe, "-test.run=^TestMainProcessHelper$", "--", "harness-process")
			cmd.Dir = root
			cmd.Env = append(os.Environ(), "GORACE=atexit_sleep_ms=0")
			var output bytes.Buffer
			cmd.Stdout, cmd.Stderr = &output, &output
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			done := make(chan error, 1)
			go func() { done <- cmd.Wait() }()
			t.Cleanup(func() { _ = cmd.Process.Kill() })
			deadline := time.Now().Add(5 * time.Second)
			for !checkpoint.Load() && time.Now().Before(deadline) {
				time.Sleep(5 * time.Millisecond)
			}
			if !checkpoint.Load() {
				t.Fatal("runner did not start")
			}
			if err := cmd.Process.Signal(signal); err != nil {
				t.Fatal(err)
			}
			select {
			case err := <-done:
				if err != nil {
					t.Fatal("signal shutdown failed", err, output.String())
				}
			case <-time.After(3 * time.Second):
				t.Fatal("harness ignored signal")
			}
			worktree := filepath.Join(filepath.Dir(root), "repository-task-task")
			checkStopped(t, worktree, "runner.pid")
			checkStopped(t, worktree, "runner-child.pid")
			if strings.Contains(output.String(), "secret-agent-token") {
				t.Fatal("token leaked")
			}
			before := heartbeat.Load()
			time.Sleep(350 * time.Millisecond)
			if heartbeat.Load() != before {
				t.Fatal("heartbeat leaked")
			}
			state := testutil.Read(t, filepath.Join(root, ".git", "agents-flow-harness", "state.json"))
			if !strings.Contains(state, "running") {
				t.Fatal("checkpoint lost on signal")
			}
		})
	}
}
