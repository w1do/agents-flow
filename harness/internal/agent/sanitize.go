package agent

import (
	"encoding/json"
	"regexp"
	"strings"

	"agentsflow/harness/internal/jsonx"
)

const maxCheckpointBytes = 256 << 10
const maxReportBytes = 1 << 20
const maxTestEvents = 50
const maxTestBytes = 256 << 10

var authSecret = regexp.MustCompile(`(?i)\b(?:Bearer|Basic|Token)\s+[^\s"']+`)

var sensitiveKeys = map[string]bool{
	"apikey": true, "accesstoken": true, "refreshtoken": true, "clientsecret": true,
	"password": true, "secret": true, "authorization": true, "agenttoken": true,
	"privatekey": true, "token": true, "key": true,
}

func sanitizeJSON(data []byte) []byte {
	return sanitizeJSONWithToken(data, "")
}

func sanitizeJSONWithToken(data []byte, knownToken string) []byte {
	var value any
	if jsonx.Unmarshal(data, &value) != nil {
		return []byte(`"[redacted]"`)
	}
	if knownToken == "" {
		knownToken = findAgentToken(value)
	}
	value = newRedactor(knownToken).value(value, "")
	clean, err := json.Marshal(value)
	if err != nil {
		return []byte(`"[redacted]"`)
	}
	return clean
}

func normalizeKey(key string) string {
	return strings.Map(func(r rune) rune {
		if r >= 'A' && r <= 'Z' {
			return r + ('a' - 'A')
		}
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, key)
}

func findAgentToken(value any) string {
	if object, ok := value.(map[string]any); ok {
		for key, item := range object {
			if normalizeKey(key) == "agenttoken" {
				if token, ok := item.(string); ok && token != "" {
					return token
				}
			}
		}
		for _, item := range object {
			if token := findAgentToken(item); token != "" {
				return token
			}
		}
	}
	if list, ok := value.([]any); ok {
		for _, item := range list {
			if token := findAgentToken(item); token != "" {
				return token
			}
		}
	}
	return ""
}

func truncateReport(data []byte) []byte {
	if len(data) <= maxReportBytes {
		return data
	}
	var value map[string]any
	if jsonx.Unmarshal(data, &value) != nil {
		return []byte(`{}`)
	}
	for key := range value {
		switch key {
		case "lease_id", "event_id", "event_type", "success", "exit_code":
		case "payload", "checkpoint", "result_data", "tests":
			value[key] = map[string]any{"truncated": true, "message": "Report field truncated because the size limit was exceeded"}
		default:
			value[key] = "Report field truncated because the size limit was exceeded"
		}
	}
	clean, err := json.Marshal(value)
	if err != nil || len(clean) > maxReportBytes {
		return []byte(`{"lease_id":"","event_id":"","message":"Report truncated because it exceeded the size limit"}`)
	}
	return clean
}
