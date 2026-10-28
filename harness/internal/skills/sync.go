package skills

import (
	"context"
	"errors"
	"sync"

	"agentsflow/harness/internal/api"
)

var ErrActive = errors.New("skills cannot change during an active task")

type Source interface {
	Skills(context.Context, string) ([]api.Skill, error)
}

type Synchronizer struct {
	mu           sync.Mutex
	active       bool
	dir, agentID string
	source       Source
}

func New(dir, agentID string, source Source) *Synchronizer {
	return &Synchronizer{dir: dir, agentID: agentID, source: source}
}

// SetActive serializes task boundaries with the entire sync operation.
// Part B must set this before handing any skill files to the task runner.
func (s *Synchronizer) SetActive(active bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.active = active
}

func (s *Synchronizer) Sync(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.active {
		return ErrActive
	}
	files, err := s.source.Skills(ctx, s.agentID)
	if err != nil {
		return err
	}
	return Apply(s.dir, files)
}
