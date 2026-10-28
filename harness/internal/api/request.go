package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"agentsflow/harness/internal/jsonx"
)

// Request keeps one idempotency key across retries. Supply key to resume a write.
// 4xx (including 409 and 429) are returned immediately to the caller.
func (c *Client) Request(ctx context.Context, method, path, key string, input, output any) (int, error) {
	if len(path) == 0 || path[0] != '/' {
		return 0, errors.New("API path must start with /")
	}
	body, err := json.Marshal(input)
	if err != nil {
		return 0, errors.New("cannot encode API request")
	}
	if method == http.MethodGet || method == http.MethodHead {
		body = nil
	}
	if key == "" && method != http.MethodGet && method != http.MethodHead {
		key = NewKey()
	}
	delay := min(c.backoff, 2*time.Second)
	for attempt := 0; attempt < c.attempts; attempt++ {
		status, data, retry, err := c.once(ctx, method, path, key, body)
		if ctx.Err() != nil {
			return status, ctx.Err()
		}
		if retry && attempt+1 < c.attempts {
			if err := wait(ctx, delay); err != nil {
				return status, err
			}
			delay = min(delay*2, 2*time.Second)
			continue
		}
		if err != nil {
			return status, err
		}
		if output != nil && status != http.StatusNoContent {
			if err := jsonx.Unmarshal(data, output); err != nil {
				return status, errors.New("invalid API response")
			}
		}
		return status, nil
	}
	return 0, errors.New("API attempts exhausted")
}

func (c *Client) once(ctx context.Context, method, path, key string, body []byte) (int, []byte, bool, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, bytes.NewReader(body))
	if err != nil {
		return 0, nil, false, errors.New("invalid API request")
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	response, err := c.http.Do(req)
	if err != nil {
		return 0, nil, true, errors.New("server connection failed or timed out")
	}
	defer response.Body.Close()
	status := response.StatusCode
	if status < 200 || status >= 300 {
		return status, nil, status >= 500, responseError(response)
	}
	const maxBody = 16 << 20
	data, err := io.ReadAll(io.LimitReader(response.Body, maxBody+1))
	if err != nil {
		return status, nil, true, errors.New("cannot read API response")
	}
	if len(data) > maxBody {
		return status, nil, false, errors.New("API response too large")
	}
	return status, data, false, nil
}
