//go:build linux

package procguard

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Only the dedicated supervisor's direct children are inspected, on SIGCHLD or
// shutdown. Kernel subreaper adoption, rather than periodic polling, owns them.
func ownedChildren() ([]int, error) {
	threads, err := os.ReadDir("/proc/self/task")
	if err != nil {
		return nil, err
	}
	var result []int
	for _, thread := range threads {
		data, err := os.ReadFile(filepath.Join("/proc/self/task", thread.Name(), "children"))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, err
		}
		for _, field := range strings.Fields(string(data)) {
			pid, err := strconv.Atoi(field)
			if err != nil {
				return nil, err
			}
			result = append(result, pid)
		}
	}
	return result, nil
}
