package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

type InitRequest struct {
	ProjectID          string `json:"project_id"`
	InitCode           string `json:"init_code"`
	AgentName          string `json:"agent_name"`
	RepositoryPathHint string `json:"repository_path_hint,omitempty"`
	GitRemote          string `json:"git_remote,omitempty"`
}

type InitResponse struct {
	AgentID             string  `json:"agent_id"`
	AgentToken          string  `json:"agent_token"`
	ServerURL           string  `json:"server_url"`
	PollIntervalSeconds int     `json:"poll_interval_seconds"`
	LeaseTTLSeconds     int     `json:"lease_ttl_seconds"`
	Skills              []Skill `json:"skills"`
}

type Skill struct {
	SkillID                string `json:"skill_id"`
	Category               string `json:"category"`
	Name                   string `json:"name"`
	Filename               string `json:"filename"`
	Version                int    `json:"version"`
	ContentHash            string `json:"content_hash"`
	Content                string `json:"content"`
	SnapshotContentMissing bool   `json:"snapshot_content_missing"`
}

type Task struct {
	SourceType  string          `json:"source_type,omitempty"`
	SourceText  string          `json:"source_text,omitempty"`
	ProjectID   string          `json:"project_id,omitempty"`
	ID          string          `json:"id"`
	Title       string          `json:"title"`
	Description string          `json:"description"`
	Checkpoint  json.RawMessage `json:"checkpoint"`
	Status      string          `json:"status,omitempty"`
	PlanText    string          `json:"plan_text,omitempty"`
}

type ClaimResponse struct {
	Task           Task      `json:"task"`
	Skills         []Skill   `json:"skills"`
	LeaseID        string    `json:"lease_id"`
	LeaseExpiresAt time.Time `json:"lease_expires_at"`
}

type HeartbeatRequest struct {
	TaskID  *string `json:"task_id"`
	LeaseID *string `json:"lease_id"`
}

type HeartbeatResponse struct {
	Status         string     `json:"status"`
	LeaseExpiresAt *time.Time `json:"lease_expires_at"`
}

func (c *Client) Init(ctx context.Context, input InitRequest) (InitResponse, error) {
	var result InitResponse
	_, err := c.Request(ctx, http.MethodPost, "/api/v1/harness/init", "", input, &result)
	return result, err
}

func agentPath(id, suffix string) string {
	return "/api/v1/agents/" + url.PathEscape(id) + "/" + suffix
}

func (c *Client) Skills(ctx context.Context, id string) ([]Skill, error) {
	var result struct {
		Skills []Skill `json:"skills"`
	}
	_, err := c.Request(ctx, http.MethodGet, agentPath(id, "skills/sync"), "", nil, &result)
	return result.Skills, err
}

func (c *Client) Claim(ctx context.Context, id, key string) (*ClaimResponse, error) {
	var result ClaimResponse
	status, err := c.Request(ctx, http.MethodPost, agentPath(id, "leases/claim"), key, struct{}{}, &result)
	if err != nil || status == http.StatusNoContent {
		return nil, err
	}
	if result.Task.ID == "" || result.LeaseID == "" || result.LeaseExpiresAt.IsZero() {
		return nil, fmt.Errorf("invalid claim response")
	}
	return &result, nil
}

func (c *Client) Heartbeat(ctx context.Context, id string, input HeartbeatRequest) (HeartbeatResponse, error) {
	var result HeartbeatResponse
	if (input.TaskID == nil) != (input.LeaseID == nil) {
		return result, fmt.Errorf("heartbeat task_id and lease_id must be paired")
	}
	_, err := c.Request(ctx, http.MethodPost, agentPath(id, "heartbeat"), "", input, &result)
	if err == nil && result.Status != "online" && result.Status != "busy" {
		err = fmt.Errorf("invalid heartbeat response")
	}
	return result, err
}
