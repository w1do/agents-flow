package bootstrap

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"

	"agentsflow/harness/internal/api"
	"agentsflow/harness/internal/config"
	"agentsflow/harness/internal/testutil"
)

func TestInitCreatesOnlyWorkflowAndIgnoresToken(t *testing.T) {
	root := testutil.Repository(t)
	testutil.Write(t, filepath.Join(root, "tracked.txt"), "dirty main")
	head := testutil.Git(t, root, "rev-parse", "HEAD")
	nested := filepath.Join(root, "nested")
	if err := os.Mkdir(nested, 0755); err != nil {
		t.Fatal(err)
	}
	var serverURL string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body api.InitRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		if r.Method != "POST" || r.URL.Path != "/api/v1/harness/init" || r.Header.Get("Authorization") != "" {
			t.Error("invalid init request")
		}
		if body.ProjectID != "project" || body.InitCode != "init-secret" || body.AgentName != "test agent" ||
			body.GitRemote != "https://example.invalid/project.git" || body.RepositoryPathHint != root {
			t.Error("init request fields do not match repository")
		}
		w.WriteHeader(201)
		_ = json.NewEncoder(w).Encode(api.InitResponse{
			AgentID: "agent", AgentToken: "private-agent-token", ServerURL: serverURL,
			PollIntervalSeconds: 5, LeaseTTLSeconds: 60,
			Skills: []api.Skill{{Name: "Display name", Filename: "test--skill.md", Version: 1, Content: "skill body"}},
		})
	}))
	defer server.Close()
	serverURL = server.URL
	if err := Init(context.Background(), Options{nested, server.URL, "project", "test agent",
		func() (string, error) { return "init-secret", nil }}); err != nil {
		t.Fatal(err)
	}
	cfg, token, err := config.Load(root)
	if err != nil || token != "private-agent-token" || cfg.AgentID != "agent" || cfg.GitRemote != "origin" {
		t.Fatal("invalid saved configuration", err)
	}
	var tree []string
	err = filepath.WalkDir(filepath.Join(root, "workflow"), func(path string, _ os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		tree = append(tree, rel)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"workflow", "workflow/.agent-token", "workflow/.gitignore", "workflow/config.yaml",
		"workflow/skills", "workflow/skills/test--skill.md"}
	sort.Strings(want)
	sort.Strings(tree)
	if !reflect.DeepEqual(tree, want) {
		t.Fatalf("unexpected init tree: %v", tree)
	}
	status := testutil.Git(t, root, "status", "--porcelain", "--untracked-files=all")
	if strings.Contains(status, ".agent-token") || strings.Contains(status, "nested/") {
		t.Fatal("token visible or nested directory modified", status)
	}
	for _, line := range strings.Split(status, "\n") {
		if !strings.HasSuffix(line, "tracked.txt") && !strings.HasPrefix(line, "?? workflow/") {
			t.Fatal("init created files outside workflow", line)
		}
	}
	if testutil.Git(t, root, "check-ignore", "workflow/.agent-token") != "workflow/.agent-token" ||
		testutil.Git(t, root, "branch", "--show-current") != "main" ||
		testutil.Git(t, root, "rev-parse", "HEAD") != head || testutil.Read(t, filepath.Join(root, "tracked.txt")) != "dirty main" {
		t.Fatal("token not ignored or primary copy changed")
	}
}
