package leases

import (
	"context"
	"errors"
	"testing"
	"time"

	"agentsflow/harness/internal/api"
)

func TestHeartbeatIndependentOfClaimAndCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	entered, unblock := make(chan struct{}), make(chan struct{})
	beats := make(chan api.HeartbeatRequest, 10)
	m := New(server{
		claim: func(context.Context, string, string) (*api.ClaimResponse, error) {
			close(entered)
			<-unblock
			return claimed(), nil
		},
		beat: func(_ context.Context, _ string, input api.HeartbeatRequest) (api.HeartbeatResponse, error) {
			beats <- input
			return api.HeartbeatResponse{Status: "online"}, nil
		},
	}, "agent")
	claimDone := make(chan struct{})
	go func() {
		defer close(claimDone)
		if _, err := m.Claim(ctx); err != nil {
			t.Error(err)
		}
	}()
	<-entered
	errorsOut := m.StartHeartbeat(ctx, 10*time.Millisecond)
	select {
	case input := <-beats:
		if input.TaskID != nil || input.LeaseID != nil {
			t.Error("idle heartbeat must send null IDs")
		}
	case <-time.After(time.Second):
		t.Error("heartbeat blocked behind claim")
	}
	close(unblock)
	<-claimDone
	deadline := time.After(time.Second)
	active := false
	for !active {
		select {
		case input := <-beats:
			active = input.TaskID != nil && *input.TaskID == "task" && input.LeaseID != nil && *input.LeaseID == "lease"
		case <-deadline:
			t.Fatal("heartbeat did not pick up active lease")
		}
	}
	cancel()
	select {
	case _, open := <-errorsOut:
		if open {
			t.Fatal("unexpected heartbeat error")
		}
	case <-time.After(time.Second):
		t.Fatal("heartbeat did not stop")
	}
}

func TestHeartbeatFailurePreservesStateAndLeaseLossStops(t *testing.T) {
	failure := errors.New("offline")
	m := New(server{
		claim: func(context.Context, string, string) (*api.ClaimResponse, error) { return claimed(), nil },
		beat: func(context.Context, string, api.HeartbeatRequest) (api.HeartbeatResponse, error) {
			return api.HeartbeatResponse{}, failure
		},
	}, "agent")
	ctx := context.Background()
	if _, err := m.Claim(ctx); err != nil {
		t.Fatal(err)
	}
	if err := m.Heartbeat(ctx); err == nil || m.State().TaskID != "task" || m.State().Lost {
		t.Fatal("connection failure discarded lease state")
	}
	failure = &api.Error{StatusCode: 409}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	errorsOut := m.StartHeartbeat(ctx, time.Millisecond)
	select {
	case err := <-errorsOut:
		if !errors.Is(err, ErrLeaseLost) || !m.State().Lost {
			t.Fatal("409 did not mark lease lost", err)
		}
	case <-time.After(time.Second):
		t.Fatal("lost lease not reported")
	}
	if _, open := <-errorsOut; open {
		t.Fatal("heartbeat kept running after lease loss")
	}
	if _, err := m.Claim(ctx); !errors.Is(err, ErrBusy) {
		t.Fatal("lost lease state must require explicit release")
	}
}
