package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAgentContracts(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			t.Error("missing agent token")
		}
		switch r.URL.Path {
		case "/api/v1/agents/agent/skills/sync":
			if r.Method != "GET" {
				t.Error("skills method")
			}
			_, _ = w.Write([]byte(`{"skills":[{"name":"Display name","filename":"test--skill.md","version":2,"content":"body"}]}`))
		case "/api/v1/agents/agent/leases/claim":
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil || len(body) != 0 {
				t.Error("claim must send an empty object", err)
			}
			w.WriteHeader(204)
		case "/api/v1/agents/agent/heartbeat":
			var body map[string]any
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil || len(body) != 2 ||
				body["task_id"] != nil || body["lease_id"] != nil {
				t.Error("idle heartbeat must send two nulls", err)
			}
			_, _ = w.Write([]byte(`{"status":"online","lease_expires_at":null}`))
		default:
			t.Error("unexpected endpoint", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	client, _ := New(server.URL, "test-token", Options{})
	ctx := context.Background()
	files, err := client.Skills(ctx, "agent")
	if err != nil || len(files) != 1 || files[0].Filename != "test--skill.md" || files[0].Version != 2 {
		t.Fatal("skills contract", err)
	}
	claim, err := client.Claim(ctx, "agent", "")
	if err != nil || claim != nil {
		t.Fatal("204 is not an error", err)
	}
	beat, err := client.Heartbeat(ctx, "agent", HeartbeatRequest{})
	if err != nil || beat.Status != "online" {
		t.Fatal("heartbeat contract", err)
	}
}

func TestRedirectDoesNotForwardToken(t *testing.T) {
	destination := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("redirect destination must not receive a request")
	}))
	defer destination.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, destination.URL, 307)
	}))
	defer server.Close()
	client, _ := New(server.URL, "test-token", Options{})
	if _, err := client.Request(context.Background(), "POST", "/test", "", nil, nil); err == nil {
		t.Fatal("redirect accepted")
	}
}

func TestURLValidation(t *testing.T) {
	for _, url := range []string{"", "file:///tmp/a", "https://user:password@host", "https://host?token=secret"} {
		if _, err := New(url, "", Options{}); err == nil {
			t.Fatal("unsafe URL accepted")
		}
	}
}
