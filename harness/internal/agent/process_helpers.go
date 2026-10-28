package agent

import "os"

func runnerEnvironment(configured map[string]string) []string {
	values := map[string]string{}
	for _, key := range []string{"PATH", "HOME", "LANG", "TZ", "TERM"} {
		if value, ok := os.LookupEnv(key); ok {
			values[key] = value
		}
	}
	for key, value := range configured {
		values[key] = value
	}
	result := make([]string, 0, len(values))
	for key, value := range values {
		result = append(result, key+"="+value)
	}
	return result
}
