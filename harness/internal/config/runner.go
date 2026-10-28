package config

import (
	"errors"
	"regexp"
	"strings"
)

type Runner struct {
	Command                []string          `yaml:"command,omitempty"`
	TimeoutSeconds         int               `yaml:"timeout_seconds,omitempty"`
	DecisionTimeoutSeconds int               `yaml:"decision_timeout_seconds,omitempty"`
	Environment            map[string]string `yaml:"environment,omitempty"`
}

var envName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

func (r Runner) validate() error {
	if r.TimeoutSeconds < 0 || r.DecisionTimeoutSeconds < 0 {
		return errors.New("runner timeouts must be positive")
	}
	if len(r.Command) > 0 && strings.TrimSpace(r.Command[0]) == "" {
		return errors.New("runner.command must start with an executable")
	}
	for key := range r.Environment {
		if !envName.MatchString(key) {
			return errors.New("runner.environment has an invalid variable name")
		}
	}
	return nil
}
