package agent

import (
	"encoding/json"
	"regexp"
	"strings"

	"agentsflow/harness/internal/api"
)

type runnerInput struct {
	ResultData map[string]any  `json:"result_data,omitempty"`
	Task       api.Task        `json:"task"`
	Stage      string          `json:"stage"`
	Path       string          `json:"path"`
	Worktree   string          `json:"worktree"`
	Branch     string          `json:"branch"`
	ReadOnly   bool            `json:"read_only"`
	Plan       string          `json:"plan_text,omitempty"`
	Feedback   string          `json:"feedback,omitempty"`
	Checkpoint json.RawMessage `json:"checkpoint"`
	Skills     []api.Skill     `json:"skills"`
}

type runnerEvent struct {
	Type          string          `json:"type"`
	Message       string          `json:"message"`
	PlanText      string          `json:"plan_text"`
	ResultSummary string          `json:"result_summary"`
	ResultData    map[string]any  `json:"result_data"`
	Payload       map[string]any  `json:"payload"`
	Checkpoint    json.RawMessage `json:"checkpoint"`
	Command       string          `json:"command"`
	ExitCode      int             `json:"exit_code"`
	Summary       string          `json:"summary"`
	Success       *bool           `json:"success"`
}

func publicationSkill(skill api.Skill) bool {
	category := skillCategory(skill)
	return strings.HasPrefix(category, "git") || strings.HasPrefix(category, "deploy") ||
		strings.HasPrefix(category, "деплой") || strings.HasPrefix(category, "публикац")
}

var categorySeparators = regexp.MustCompile(`[\s_]+`)

func skillCategory(skill api.Skill) string {
	category := skill.Category
	if category == "" {
		name := skill.Filename
		if name == "" {
			name = skill.Name
		}
		category = strings.SplitN(name, "--", 2)[0]
	}
	return categorySeparators.ReplaceAllString(strings.ToLower(strings.TrimSpace(category)), "-")
}

func stageSkills(files []api.Skill, stage string) []api.Skill {
	result := make([]api.Skill, 0, len(files))
	for _, file := range files {
		if stage == "publication" {
			if publicationSkill(file) {
				result = append(result, file)
			}
		} else if !publicationSkill(file) {
			category := skillCategory(file)
			if stage != "testing" || category == "testing" || category == "test" || strings.HasPrefix(category, "тест") {
				result = append(result, file)
			}
		}
	}
	return result
}

func (e *Engine) input() runnerInput {
	task := e.state.Claim.Task
	task.Checkpoint = nil // Raw task snapshots must not bypass stage skill filtering.
	return runnerInput{Task: task, Stage: e.state.Stage, Path: e.state.Worktree, Worktree: e.state.Worktree,
		Branch: "task/" + task.ID, ReadOnly: e.state.Stage == "planning", Plan: e.state.Plan, Feedback: e.state.Feedback,
		Checkpoint: e.state.Checkpoint, Skills: stageSkills(e.state.Claim.Skills, e.state.Stage), ResultData: e.state.ResultData}
}
