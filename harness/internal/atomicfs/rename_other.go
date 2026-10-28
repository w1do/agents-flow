//go:build !linux

package atomicfs

import (
	"errors"
	"os"
)

func rename(*os.Root, string, string) error {
	return errors.New("pinned atomic replacement currently requires Linux")
}
