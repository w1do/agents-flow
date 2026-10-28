package agent

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"agentsflow/harness/internal/api"
)

type recordedReport struct {
	kind, key string
	body      map[string]json.RawMessage
}

type flowServer struct {
	mu                                                       sync.Mutex
	t                                                        *testing.T
	server                                                   *httptest.Server
	status, planDecision, decision, resultDecision           string
	claimed, completed                                       bool
	claims, syncs, heartbeats, planPolls, resultPolls, round int
	taskHeartbeats                                           int
	reports                                                  []recordedReport
	seen                                                     map[string][]byte
	checkpoint                                               json.RawMessage
	faultPath                                                string
	faultCode, faultRemaining                                int
	firstFaultKey                                            string
	loseHeartbeat                                            bool
	missingPublicationSnapshot                               bool
	commitFault                                              bool
	faultNeedle                                              string
}

func newFlowServer(t *testing.T, decision string) *flowServer {
	s := &flowServer{t: t, status: "choosing", planDecision: "pending", decision: decision, seen: map[string][]byte{}}
	s.server = httptest.NewServer(http.HandlerFunc(s.serve))
	t.Cleanup(s.server.Close)
	return s
}

func assignedSkills() []api.Skill {
	return []api.Skill{
		{Category: "development", Filename: "development--one.md", Content: "Development"},
		{Category: "testing", Filename: "testing--one.md", Content: "Testing"},
		{Category: "git", Filename: "git--one.md", Content: "publication-secret"},
		{Category: "deploy", Filename: "deploy--one.md", Content: "publication-secret"},
	}
}

func (s *flowServer) serve(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if r.Header.Get("Authorization") != "Bearer agent-secret" {
		s.t.Error("missing authorization")
	}
	path := r.URL.Path
	if strings.HasSuffix(path, "/skills/sync") {
		s.syncs++
		if s.claimed && !s.completed {
			s.t.Error("skills synced during active task")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"skills": assignedSkills()})
		return
	}
	if strings.HasSuffix(path, "/heartbeat") {
		s.heartbeats++
		var body api.HeartbeatRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.TaskID != nil {
			s.taskHeartbeats++
		}
		if (body.TaskID == nil) != (body.LeaseID == nil) || body.TaskID != nil && (*body.TaskID != "task" || *body.LeaseID != "lease") {
			s.t.Error("invalid task heartbeat")
		}
		if s.loseHeartbeat && body.TaskID != nil {
			w.WriteHeader(409)
			return
		}
		status := "online"
		if s.claimed && !s.completed {
			status = "busy"
		}
		_ = json.NewEncoder(w).Encode(api.HeartbeatResponse{Status: status})
		return
	}
	if strings.HasSuffix(path, "/leases/claim") {
		s.claims++
		if s.claimed {
			w.WriteHeader(204)
			return
		}
		s.claimed = true
		skills := assignedSkills()
		if s.missingPublicationSnapshot {
			skills[2].SnapshotContentMissing = true
		}
		_ = json.NewEncoder(w).Encode(api.ClaimResponse{Task: api.Task{ID: "task", Status: s.status, Checkpoint: s.checkpoint},
			Skills: skills, LeaseID: "lease", LeaseExpiresAt: time.Now().Add(time.Minute)})
		return
	}
	if strings.HasSuffix(path, "/execution-state") {
		if r.URL.Query().Get("lease_id") != "lease" {
			s.t.Error("execution-state lease missing")
		}
		s.execution(w)
		return
	}
	data, _ := io.ReadAll(r.Body)
	key := r.Header.Get("Idempotency-Key")
	var body map[string]json.RawMessage
	if json.Unmarshal(data, &body) != nil || string(body["lease_id"]) != `"lease"` || string(body["event_id"]) != `"`+key+`"` || key == "" {
		s.t.Error("report is missing required identity")
	}
	if old, ok := s.seen[key]; ok && !bytes.Equal(old, data) {
		s.t.Error("retry changed report body")
	}
	s.seen[key] = data
	kind := path[strings.LastIndex(path, "/")+1:]
	if kind == s.faultPath && s.faultRemaining > 0 && bytes.Contains(data, []byte(s.faultNeedle)) {
		if s.firstFaultKey == "" {
			s.firstFaultKey = key
		} else if key != s.firstFaultKey {
			s.t.Error("retry changed key")
		}
		s.faultRemaining--
		if s.commitFault {
			s.record(httptest.NewRecorder(), kind, key, body)
		}
		w.WriteHeader(s.faultCode)
		return
	}
	s.record(w, kind, key, body)
}
