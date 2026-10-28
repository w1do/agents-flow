package agent

import (
	"encoding/json"
	"net/http"

	"agentsflow/harness/internal/api"
)

func (s *flowServer) execution(w http.ResponseWriter) {
	planFeedback := ""
	if s.status == "backlog" {
		s.planPolls++
		if s.planPolls > 1 {
			if s.decision == "rejected" {
				s.status, s.planDecision = "planning", "rejected"
			} else if s.decision == "rejected-once" && s.planPolls == 2 {
				s.status, s.planDecision = "planning", "rejected"
				planFeedback = "Please revise plan"
			} else if s.decision == "trash" {
				s.status = "trash"
			} else if s.decision != "pending-plan" {
				s.status, s.planDecision = "active", "approved"
			}
		}
	}
	if s.status == "ready" {
		s.resultPolls++
		if s.resultPolls > 1 {
			switch s.decision {
			case "rework":
				if s.round == 1 {
					s.status, s.resultDecision = "active", "rework"
				} else {
					s.status, s.resultDecision = "merged", "publish"
				}
			case "keep_ready":
				s.resultDecision = "keep_ready"
			default:
				s.status, s.resultDecision = "merged", "publish"
			}
		}
	}
	_ = json.NewEncoder(w).Encode(api.ExecutionState{TaskID: "task", LeaseID: "lease", Status: s.status,
		PlanDecision: s.planDecision, PlanFeedback: planFeedback, ResultDecision: s.resultDecision, PublicationRequested: s.status == "merged" && !s.completed,
		ResultFeedback: "Please revise", Checkpoint: s.checkpoint})
}

func (s *flowServer) record(w http.ResponseWriter, kind, key string, body map[string]json.RawMessage) {
	for _, old := range s.reports {
		if old.key == key {
			_, _ = w.Write([]byte(`{}`))
			return
		}
	}
	allowed := map[string][]string{
		"events": {"lease_id", "event_id", "event_type", "message", "payload", "checkpoint"},
		"plan":   {"lease_id", "event_id", "plan_text"}, "result": {"lease_id", "event_id", "result_summary", "result_data"},
		"fail": {"lease_id", "event_id", "message", "payload"}, "publication-result": {"lease_id", "event_id", "success", "message", "payload"},
	}
	fields, ok := allowed[kind]
	if !ok {
		s.t.Error("unknown report", kind)
		w.WriteHeader(404)
		return
	}
	for field := range body {
		valid := false
		for _, name := range fields {
			if name == field {
				valid = true
			}
		}
		if !valid {
			s.t.Error("unknown report field", kind, field)
			w.WriteHeader(422)
			return
		}
	}
	switch kind {
	case "events":
		var payload map[string]json.RawMessage
		_ = json.Unmarshal(body["payload"], &payload)
		if payload["status"] != nil {
			s.t.Error("runner attempted a status transition")
		}
		var eventType string
		_ = json.Unmarshal(body["event_type"], &eventType)
		if eventType == "planning" {
			if s.status != "choosing" {
				s.t.Error("invalid planning transition", s.status)
			}
			s.status = "planning"
		}
		if eventType == "testing" {
			if s.status != "active" {
				s.t.Error("invalid testing transition", s.status)
			}
			s.status = "testing"
		}
		s.checkpoint = body["checkpoint"]
	case "plan":
		if s.status != "planning" {
			s.t.Error("plan before planning")
		}
		s.status, s.planDecision = "backlog", "pending"
	case "result":
		if s.status != "testing" {
			s.t.Error("result before testing")
		}
		s.status = "ready"
		s.round++
		s.resultPolls = 0
	case "publication-result":
		if s.status != "merged" {
			s.t.Error("publication before approval")
		}
		s.completed = true
	case "fail":
		s.status, s.completed = "error", true
	}
	s.reports = append(s.reports, recordedReport{kind, key, body})
	_, _ = w.Write([]byte(`{}`))
}
