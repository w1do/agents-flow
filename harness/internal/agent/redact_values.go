package agent

import (
	"sort"
	"strconv"
)

func (r *redactor) value(value any, key string) any {
	if sensitiveKeys[normalizeKey(key)] {
		return redacted
	}
	switch value := value.(type) {
	case map[string]any:
		clean := make(map[string]any, len(value))
		nextSuffix := make(map[string]int)
		keys := make([]string, 0, len(value))
		for key := range value {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			base := r.text(key)
			name := base
			if _, exists := clean[name]; exists {
				suffix := nextSuffix[base]
				if suffix < 2 {
					suffix = 2
				}
				for {
					name = base + "#" + strconv.Itoa(suffix)
					suffix++
					if _, exists := clean[name]; !exists {
						break
					}
				}
				nextSuffix[base] = suffix
			}
			clean[name] = r.value(value[key], key)
		}
		return clean
	case []any:
		clean := make([]any, len(value))
		for i := range value {
			clean[i] = r.value(value[i], "")
		}
		return clean
	case string:
		return r.text(value)
	default:
		return value
	}
}
