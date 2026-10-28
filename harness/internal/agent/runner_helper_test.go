package agent

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// This test is also the external helper executable. Harness sees only JSON I/O.
func TestRunnerHelper(t *testing.T) {
	mode := ""
	for i, arg := range os.Args {
		if arg == "--" && i+1 < len(os.Args) {
			mode = os.Args[i+1]
			break
		}
	}
	if mode == "" {
		return
	}
	if mode == "sleep-child" {
		time.Sleep(time.Hour)
		os.Exit(0)
	}
	var input runnerInput
	data, readErr := io.ReadAll(os.Stdin)
	if readErr != nil || json.Unmarshal(data, &input) != nil {
		os.Exit(20)
	}
	if os.Getenv("AGENTS_FLOW_INIT_TOKEN") != "" || os.Getenv("AGENTS_FLOW_AGENT_TOKEN") != "" {
		os.Exit(21)
	}
	for _, skill := range input.Skills {
		publication := skill.Category == "git" || skill.Category == "deploy"
		if publication != (input.Stage == "publication") {
			os.Exit(22)
		}
	}
	if input.Stage != "publication" && bytes.Contains(data, []byte("publication-secret")) {
		os.Exit(22)
	}
	if input.Worktree != input.Path || input.Branch != "task/"+input.Task.ID {
		os.Exit(23)
	}
	if mode == "malformed" {
		_, _ = os.Stdout.WriteString("invalid-json\n")
		os.Exit(0)
	}
	if mode == "no-terminal" {
		os.Exit(0)
	}
	emit := func(value runnerEvent) {
		if json.NewEncoder(os.Stdout).Encode(value) != nil {
			os.Exit(24)
		}
	}
	switch input.Stage {
	case "planning":
		if !input.ReadOnly {
			os.Exit(25)
		}
		if mode == "plan-feedback" && input.Feedback != "Please revise plan" && input.Feedback != "" {
			os.Exit(34)
		}
		emit(runnerEvent{Type: "plan", PlanText: "Approved plan"})
	case "implementation":
		if input.Plan != "Approved plan" || input.ReadOnly {
			os.Exit(26)
		}
		if mode == "resume" && !strings.Contains(string(input.Checkpoint), "saved-step") {
			os.Exit(27)
		}
		if mode == "feedback" && input.Feedback != "Please revise" {
			os.Exit(28)
		}
		if input.Feedback != "" {
			_ = os.WriteFile("feedback.txt", []byte(input.Feedback), 0600)
		}
		if os.WriteFile("change.txt", []byte("task progress"), 0600) != nil {
			os.Exit(29)
		}
		if mode != "block" && mode != "descendant" {
			emit(runnerEvent{Type: "progress", Message: "Saved", Payload: map[string]any{"status": "runner-state"}, Checkpoint: json.RawMessage(`{"step":"saved-step"}`)})
		}
		if mode == "failure" {
			emit(runnerEvent{Type: "failure", Message: "runner reason"})
			os.Exit(0)
		}
		if mode == "large-checkpoint" {
			checkpoint, _ := json.Marshal(map[string]string{"payload": strings.Repeat("x", 300<<10)})
			emit(runnerEvent{Type: "progress", Message: "Large checkpoint", Checkpoint: checkpoint})
		}
		if mode == "exit" {
			os.Exit(17)
		}
		if mode == "block" || mode == "descendant" {
			exe, _ := os.Executable()
			child := exec.Command(exe, "-test.run=^TestRunnerHelper$", "--", "sleep-child")
			child.Stdout = os.Stdout
			if child.Start() != nil {
				os.Exit(30)
			}
			_ = os.WriteFile("descendant.pid", []byte(strconv.Itoa(child.Process.Pid)), 0600)
			emit(runnerEvent{Type: "progress", Message: "Saved", Checkpoint: json.RawMessage(`{"step":"saved-step"}`)})
			if mode == "block" {
				time.Sleep(time.Hour)
			}
			os.Exit(0)
		}
		emit(runnerEvent{Type: "result", ResultSummary: "Implemented", ResultData: map[string]any{"implementation": "kept"}})
	case "testing":
		if _, err := os.Stat(filepath.Join(input.Worktree, "change.txt")); err != nil {
			os.Exit(31)
		}
		emit(runnerEvent{Type: "test_result", Command: "configured check", ExitCode: 0, Summary: "passed"})
		emit(runnerEvent{Type: "result", ResultSummary: "Ready", ResultData: map[string]any{"changed_paths": []string{"change.txt"}}})
	case "publication":
		if mode == "publication-failure" {
			emit(runnerEvent{Type: "failure"})
			os.Exit(17)
		}
		if len(input.Skills) != 2 {
			os.Exit(32)
		}
		success := true
		emit(runnerEvent{Type: "result", Success: &success, Message: "Published", ResultData: map[string]any{"revision": "test-revision"}})
	default:
		os.Exit(33)
	}
	os.Exit(0)
}
