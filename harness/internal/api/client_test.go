package api

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestRetriesAndHeaders(t *testing.T) {
	for _, status := range []int{200, 401, 403, 404, 409, 422, 429, 500, 503} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			var calls int
			var firstKey string
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				key := r.Header.Get("Idempotency-Key")
				if calls == 1 {
					firstKey = key
				}
				if key == "" || key != firstKey || r.Header.Get("Authorization") != "Bearer test-token" {
					t.Error("authorization or idempotency header missing/changed")
				}
				if r.URL.Path != "/api/v1/test" {
					t.Error("unexpected API path")
				}
				if calls < 3 {
					w.WriteHeader(status)
					return
				}
				w.WriteHeader(200)
			}))
			defer server.Close()
			client, err := New(server.URL, "test-token", Options{Backoff: time.Millisecond})
			if err != nil {
				t.Fatal(err)
			}
			start := time.Now()
			_, err = client.Request(context.Background(), "POST", "/api/v1/test", "", struct{}{}, nil)
			wantCalls := 1
			if status >= 500 {
				wantCalls = 3
				if time.Since(start) < 3*time.Millisecond {
					t.Error("retries did not back off")
				}
			}
			if calls != wantCalls {
				t.Fatalf("calls = %d, want %d", calls, wantCalls)
			}
			if status >= 400 && status < 500 {
				var apiErr *Error
				if !errors.As(err, &apiErr) || apiErr.StatusCode != status {
					t.Fatal("expected structured HTTP error", err)
				}
			} else if err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestTimeoutRetry(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			<-r.Context().Done()
			return
		}
		w.WriteHeader(204)
	}))
	defer server.Close()
	client, err := New(server.URL, "", Options{
		HTTPClient: &http.Client{Timeout: 100 * time.Millisecond}, Backoff: time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.Request(context.Background(), "GET", "/test", "", nil, nil); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 2 {
		t.Fatal("timeout was not retried")
	}
}

func TestHTTPOnlyForLoopbackOrExplicitOptIn(t *testing.T) {
	if _, err := New("http://example.com", "secret", Options{}); err == nil {
		t.Fatal("plain HTTP to a public host accepted")
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) }))
	defer server.Close()
	client, err := New(server.URL, "loopback-token", Options{})
	if err != nil {
		t.Fatal("loopback HTTP rejected", err)
	}
	if _, err := client.Request(context.Background(), http.MethodGet, "/test", "", nil, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := New("http://example.com", "secret", Options{AllowInsecure: true}); err != nil {
		t.Fatal("explicit opt-in rejected", err)
	}
}

func TestCancellationAndSecretErrors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(503)
		_, _ = w.Write([]byte("private-token skill-content"))
	}))
	defer server.Close()
	client, _ := New(server.URL, "private-token", Options{Backoff: time.Second})
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	_, err := client.Request(ctx, "POST", "/test", "", nil, nil)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("backoff did not honor cancellation", err)
	}
	client, _ = New(server.URL, "private-token", Options{MaxAttempts: 1})
	_, err = client.Request(context.Background(), "POST", "/test", "", nil, nil)
	if err == nil || strings.Contains(err.Error(), "private-token") || strings.Contains(err.Error(), "skill-content") {
		t.Fatal("expected sanitized error")
	}
}
