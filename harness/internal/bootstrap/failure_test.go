package bootstrap

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentsflow/harness/internal/testutil"
)

func TestInitFailuresLeaveNoWorkflow(t *testing.T) {
	for _, status := range []int{401, 403, 404, 409, 422} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			root := testutil.Repository(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(status)
				_, _ = w.Write([]byte("private-init-code private-agent-token"))
			}))
			defer server.Close()
			err := Init(context.Background(), Options{root, server.URL, "project", "agent",
				func() (string, error) { return "private-init-code", nil }})
			if err == nil || strings.Contains(err.Error(), "private-") {
				t.Fatal("expected sanitized rejection")
			}
			if _, err := os.Stat(filepath.Join(root, "workflow")); !os.IsNotExist(err) {
				t.Fatal("rejected init created workflow")
			}
		})
	}
}

func TestInitOutsideGitDoesNotUseNetworkOrPrompt(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("network request outside Git")
	}))
	defer server.Close()
	err := Init(context.Background(), Options{t.TempDir(), server.URL, "project", "agent",
		func() (string, error) { t.Error("prompted outside Git"); return "code", nil }})
	if err == nil {
		t.Fatal("init outside Git succeeded")
	}
}

func TestInitRefusesExistingWorkflow(t *testing.T) {
	root := testutil.Repository(t)
	dir := filepath.Join(root, "workflow")
	if err := os.Mkdir(dir, 0755); err != nil {
		t.Fatal(err)
	}
	testutil.Write(t, filepath.Join(dir, "config.yaml"), "keep")
	err := Init(context.Background(), Options{root, "http://unused.invalid", "project", "agent",
		func() (string, error) { t.Error("prompted for existing workflow"); return "code", nil }})
	if err == nil || testutil.Read(t, filepath.Join(dir, "config.yaml")) != "keep" {
		t.Fatal("existing workflow was overwritten")
	}
}

func TestInitRollsBackInvalidSkillResponse(t *testing.T) {
	root := testutil.Repository(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(201)
		_, _ = w.Write([]byte(`{"agent_id":"agent","agent_token":"private-token","server_url":"https://flow.invalid","poll_interval_seconds":5,"lease_ttl_seconds":60,"skills":[{"filename":"../escape.md","content":"unsafe"}]}`))
	}))
	defer server.Close()
	err := Init(context.Background(), Options{root, server.URL, "project", "agent",
		func() (string, error) { return "code", nil }})
	if err == nil {
		t.Fatal("unsafe skill accepted")
	}
	if _, err := os.Stat(filepath.Join(root, "workflow")); !os.IsNotExist(err) {
		t.Fatal("partial workflow was not removed")
	}
	if status := testutil.Git(t, root, "status", "--porcelain"); status != "" {
		t.Fatal("invalid init changed primary copy", status)
	}
}
