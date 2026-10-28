package leases

import "errors"

// Resume restores a locally journaled lease before heartbeat starts.
func (m *Manager) Resume(state State) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.claiming || m.state.TaskID != "" || state.TaskID == "" || state.LeaseID == "" {
		return errors.New("cannot resume lease")
	}
	m.state = state
	return nil
}

// PrepareClaim reuses a durable key after a crash between claim and its response.
func (m *Manager) PrepareClaim(key string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.claiming && m.state.TaskID == "" {
		m.claimKey = key
	}
}
