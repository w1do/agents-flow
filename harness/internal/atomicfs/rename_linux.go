//go:build linux

package atomicfs

import (
	"os"
	"syscall"
)

func rename(root *os.Root, old, new string) error {
	dir, err := root.Open(".")
	if err != nil {
		return err
	}
	defer dir.Close()
	if err := syscall.Renameat(int(dir.Fd()), old, int(dir.Fd()), new); err != nil {
		return err
	}
	return dir.Sync()
}
