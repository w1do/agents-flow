package leases

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"agentsflow/harness/internal/api"
)

type server struct {
	claim func(context.Context, string, string) (*api.ClaimResponse, error)
	beat  func(context.Context, string, api.HeartbeatRequest) (api.HeartbeatResponse, error)
}

func (s server) Claim(ctx context.Context, id, key string) (*api.ClaimResponse, error) {
	return s.claim(ctx, id, key)
}

func (s server) Heartbeat(ctx context.Context, id string, input api.HeartbeatRequest) (api.HeartbeatResponse, error) {
	return s.beat(ctx, id, input)
}

func claimed() *api.ClaimResponse {
	return &api.ClaimResponse{Task: api.Task{ID: "task"}, LeaseID: "lease", LeaseExpiresAt: time.Now().Add(time.Minute)}
}

func TestClaimImmediateEmptyAndBusy(t *testing.T) {
	calls := 0
	m := New(server{claim: func(context.Context, string, string) (*api.ClaimResponse, error) {
		calls++
		if calls == 1 {
			return nil, nil
		}
		return claimed(), nil
	}}, "agent")
	start := time.Now()
	if task, err := m.Claim(context.Background()); err != nil || task != nil {
		t.Fatal("empty claim", err)
	}
	if task, err := m.Claim(context.Background()); err != nil || task == nil {
		t.Fatal("claim task", err)
	}
	if time.Since(start) >= time.Second {
		t.Fatal("claim waited for poll interval")
	}
	if _, err := m.Claim(context.Background()); !errors.Is(err, ErrBusy) || calls != 2 {
		t.Fatal("busy agent attempted another claim")
	}
}

func TestConcurrentClaim(t *testing.T) {
	entered, proceed := make(chan struct{}), make(chan struct{})
	m := New(server{claim: func(context.Context, string, string) (*api.ClaimResponse, error) {
		close(entered)
		<-proceed
		return claimed(), nil
	}}, "agent")
	var group sync.WaitGroup
	group.Add(1)
	go func() {
		defer group.Done()
		if _, err := m.Claim(context.Background()); err != nil {
			t.Error(err)
		}
	}()
	<-entered
	if _, err := m.Claim(context.Background()); !errors.Is(err, ErrBusy) {
		t.Error("concurrent claim allowed")
	}
	close(proceed)
	group.Wait()
}

func TestClaimRetainsKeyOnConnectionFailure(t *testing.T) {
	var first string
	calls := 0
	m := New(server{claim: func(_ context.Context, _, key string) (*api.ClaimResponse, error) {
		calls++
		if calls == 1 {
			first = key
			return nil, errors.New("offline")
		}
		if key != first || key == "" {
			t.Error("idempotency key changed after ambiguous failure")
		}
		return claimed(), nil
	}}, "agent")
	_, _ = m.Claim(context.Background())
	if _, err := m.Claim(context.Background()); err != nil {
		t.Fatal(err)
	}
}

func TestRemoteBusy(t *testing.T) {
	calls := 0
	m := New(server{
		claim: func(context.Context, string, string) (*api.ClaimResponse, error) {
			calls++
			return nil, &api.Error{StatusCode: 409}
		},
		beat: func(context.Context, string, api.HeartbeatRequest) (api.HeartbeatResponse, error) {
			return api.HeartbeatResponse{Status: "online"}, nil
		},
	}, "agent")
	for range 2 {
		if _, err := m.Claim(context.Background()); !errors.Is(err, ErrBusy) {
			t.Fatal("server busy not respected")
		}
	}
	if calls != 1 {
		t.Fatal("repeated claim while server reported busy")
	}
	if err := m.Heartbeat(context.Background()); err != nil {
		t.Fatal(err)
	}
	_, _ = m.Claim(context.Background())
	if calls != 2 {
		t.Fatal("online heartbeat did not clear remote busy state")
	}
}
