package agent

import (
	"path/filepath"
	"reflect"
	"testing"
)

func TestRunnerTimeoutReportsFailure(t *testing.T) {
	s := newFlowServer(t, "publish")
	e, root := fixture(t, s, "block")
	e.cfg.Runner.TimeoutSeconds = 5
	cancel, done := start(t, e)
	await(t, s, func(s *flowServer) bool { return s.completed && s.claims > 1 })
	cancel()
	<-done
	assertDescendantStopped(t, filepath.Join(filepath.Dir(root), "repository-task-task"))
	if got := reportKinds(s); !reflect.DeepEqual(got, []string{"plan", "fail"}) {
		t.Fatal("runner timeout was not reported", got)
	}
}
