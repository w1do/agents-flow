package cli

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/agent"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/testutil"
)

func TestCLIInitAndRun(t *testing.T) {
	for _, fromEnv := range []bool{false, true} {
		t.Run(map[bool]string{false: "stdin", true: "environment"}[fromEnv], func(t *testing.T) {
			root := testutil.Repository(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/v1/harness/init" {
					t.Error("unexpected request")
				}
				w.WriteHeader(201)
				_, _ = w.Write([]byte(`{"agent_id":"agent","agent_token":"private-token","server_url":"https://flow.invalid","poll_interval_seconds":5,"lease_ttl_seconds":60,"skills":[]}`))
			}))
			defer server.Close()
			var output bytes.Buffer
			env := Environment{root, strings.NewReader("private-code\n"), &output, func(key string) string {
				if key == "AGENTS_FLOW_SERVER_URL" {
					return server.URL
				}
				if fromEnv && key == "AGENTS_FLOW_INIT_TOKEN" {
					return "private-code"
				}
				return ""
			}}
			args := []string{"init", "project", "--agent-name", "test agent"}
			if !fromEnv {
				args = []string{"init", "--server-url", server.URL, "project"}
			}
			if err := Execute(context.Background(), args, env); err != nil {
				t.Fatal(err)
			}
			if strings.Contains(output.String(), "private-") {
				t.Fatal("secret leaked to CLI output")
			}
			if _, _, err := config.Load(root); err != nil {
				t.Fatal(err)
			}
			if err := Execute(context.Background(), []string{"run"}, env); !errors.Is(err, agent.ErrRunnerNotConfigured) {
				t.Fatal("run must require an explicitly configured runner", err)
			}
			testutil.Write(t, filepath.Join(root, "workflow/.agent-token"), "")
			if err := Execute(context.Background(), []string{"run"}, env); err == nil || errors.Is(err, agent.ErrRunnerNotConfigured) {
				t.Fatal("run did not validate token")
			}
		})
	}
}

func TestCommandParsing(t *testing.T) {
	var out bytes.Buffer
	env := Environment{t.TempDir(), strings.NewReader(""), &out, func(string) string { return "" }}
	for _, args := range [][]string{nil, {"unknown"}, {"run", "extra"}, {"init"}, {"init", "project", "--bad"}} {
		if err := Execute(context.Background(), args, env); err == nil {
			t.Error("invalid command accepted", args)
		}
	}
	for _, args := range [][]string{{"-h"}, {"init", "-h"}, {"run", "--help"}} {
		if err := Execute(context.Background(), args, env); err != nil {
			t.Error("help command failed", err)
		}
	}
}
