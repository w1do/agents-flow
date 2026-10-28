package agent

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRunnerDrainsStdoutWhileAPIIsSlow(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		time.Sleep(80 * time.Millisecond)
		w.WriteHeader(204)
	}))
	defer server.Close()
	dir := t.TempDir()
	var stream strings.Builder
	for range 6 {
		data, _ := json.Marshal(map[string]any{"type": "progress", "message": strings.Repeat("x", 16000)})
		stream.Write(data)
		stream.WriteByte('\n')
	}
	data, _ := json.Marshal(map[string]any{"type": "result", "result_summary": strings.Repeat("terminal", 20000)})
	stream.Write(data)
	stream.WriteByte('\n')
	path := filepath.Join(dir, "events.ndjson")
	if err := os.WriteFile(path, []byte(stream.String()), 0600); err != nil {
		t.Fatal(err)
	}
	count, terminal := 0, false
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := runProcess(ctx, []string{"sh", "-c", `cat "$1"`, "runner", path}, runnerInput{Worktree: dir}, nil, func(event runnerEvent) error {
		count++
		if event.Type == "result" {
			terminal = true
			return nil
		}
		response, err := http.Get(server.URL)
		if err == nil {
			_ = response.Body.Close()
		}
		return err
	})
	if err != nil || !terminal || count != 7 {
		t.Fatalf("stdout lost: terminal=%v count=%d err=%v", terminal, count, err)
	}
}

func TestRunnerEventNumbersRemainExact(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "numbers.ndjson")
	if err := os.WriteFile(path, []byte(`{"type":"result","result_data":{"id":9007199254740993}}`+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	var number any
	err := runProcess(context.Background(), []string{"sh", "-c", `cat "$1"`, "runner", path}, runnerInput{Worktree: dir}, nil, func(event runnerEvent) error { number = event.ResultData["id"]; return nil })
	if err != nil || number != json.Number("9007199254740993") {
		t.Fatalf("runner number=%v (%T), err=%v", number, number, err)
	}
}

func TestForcedStdoutCloseIsProtocolFailure(t *testing.T) {
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	items := readEvents(context.Background(), reader)
	_ = reader.Close()
	item, open := <-items
	if !open || item.err != errRunnerProtocol {
		t.Fatal("forced close was treated as EOF", item.err)
	}
	for range items {
	}
}
