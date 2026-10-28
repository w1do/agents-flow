package api

import (
	"io"
	"net/http"

	"agentsflow/harness/internal/jsonx"
)

// Keep only an allowlisted classification, never arbitrary server diagnostics.
func responseError(response *http.Response) *Error {
	err := &Error{StatusCode: response.StatusCode}
	if response.StatusCode != http.StatusConflict {
		return err
	}
	data, readErr := io.ReadAll(io.LimitReader(response.Body, 4097))
	if readErr != nil || len(data) > 4096 {
		return err
	}
	var body struct {
		Detail string `json:"detail"`
		Code   string `json:"code"`
	}
	if jsonx.Unmarshal(data, &body) == nil {
		err.TaskFinished = body.Detail == "Task is finished" || body.Code == "task_finished"
	}
	return err
}
