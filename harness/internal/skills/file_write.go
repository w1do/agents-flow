package skills

import (
	"agentsflow/harness/internal/atomicfs"
	"os"
)

func replaceRoot(root *os.Root, name string, data []byte) error {
	return atomicfs.Write(root, name, data, 0644)
}
