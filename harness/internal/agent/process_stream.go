package agent

import (
	"bufio"
	"bytes"
	"context"
	"io"

	"agentsflow/harness/internal/jsonx"
)

type streamItem struct {
	event runnerEvent
	err   error
}

func readEvents(ctx context.Context, reader io.Reader) <-chan streamItem {
	items := make(chan streamItem, 16)
	go func() {
		defer close(items)
		scanner := bufio.NewScanner(reader)
		scanner.Buffer(make([]byte, 4096), 1<<20)
		for scanner.Scan() {
			if len(bytes.TrimSpace(scanner.Bytes())) == 0 {
				continue
			}
			var item streamItem
			if jsonx.Unmarshal(scanner.Bytes(), &item.event) != nil {
				item.err = errRunnerProtocol
			}
			select {
			case items <- item:
			case <-ctx.Done():
				return
			}
			if item.err != nil {
				return
			}
		}
		// A forced close is a broken stream, never a successful EOF.
		if scanner.Err() != nil {
			select {
			case items <- streamItem{err: errRunnerProtocol}:
			case <-ctx.Done():
			}
		}
	}()
	return items
}
