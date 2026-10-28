package gitrepo

import (
	"context"
	"strings"
)

func filterOptions(ctx context.Context, dir string) ([]string, error) {
	args := []string{"config", "--list", "--show-origin", "--includes", "--null"}
	data, err := configuredCommand(ctx, dir, nil, true, false, args...).Output()
	if err != nil {
		return nil, err
	}
	keys, worktree := configKeys(string(data))
	if worktree {
		args = append(args, "--worktree")
		extra, err := configuredCommand(ctx, dir, nil, true, false, args...).Output()
		if err != nil {
			return nil, err
		}
		more, _ := configKeys(string(extra))
		keys += more
	}
	return neutralFilters(keys), nil
}

func configKeys(config string) (string, bool) {
	fields := strings.Split(config, "\x00")
	keys, worktree := "", false
	for i := 1; i < len(fields); i += 2 {
		key, value, hasValue := strings.Cut(fields[i], "\n")
		if !hasValue {
			value = "true"
		}
		keys += key + "\x00"
		enabled := strings.ToLower(value)
		if strings.EqualFold(key, "extensions.worktreeconfig") && (enabled == "true" || enabled == "yes" || enabled == "on" || enabled == "1") {
			worktree = true
		}
	}
	return keys, worktree
}

func neutralFilters(config string) []string {
	options := []string{}
	seen := map[string]bool{}
	for _, key := range strings.Split(config, "\x00") {
		lower := strings.ToLower(key)
		// include.path is data for discovery, never a security override.
		if strings.HasPrefix(lower, "diff.") && (strings.HasSuffix(lower, ".command") || strings.HasSuffix(lower, ".textconv")) {
			options = append(options, "-c", key+"=")
		}
		if !strings.HasPrefix(lower, "filter.") {
			continue
		}
		end := strings.LastIndex(key, ".")
		if end < len("filter.") {
			continue
		}
		driver := key[:end]
		if seen[driver] {
			continue
		}
		seen[driver] = true
		for _, setting := range []string{"clean=cat", "smudge=cat", "process=", "required=false"} {
			options = append(options, "-c", driver+"."+setting)
		}
	}
	return options
}
