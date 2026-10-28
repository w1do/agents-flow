// Package atomicfs replaces directory entries without modifying existing inodes.
package atomicfs

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
)

func Write(root *os.Root, name string, data []byte, mode os.FileMode) error {
	if name == "" || name == "." || name == ".." || filepath.Base(name) != name {
		return errors.New("atomic replacement requires a single directory entry")
	}
	var random [16]byte
	_, _ = rand.Read(random[:])
	temp := ".replace-" + hex.EncodeToString(random[:])
	f, err := root.OpenFile(temp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	defer root.Remove(temp)
	modeErr := f.Chmod(mode)
	_, writeErr := f.Write(data)
	syncErr := f.Sync()
	closeErr := f.Close()
	if err := errors.Join(modeErr, writeErr, syncErr, closeErr); err != nil {
		return err
	}
	return rename(root, temp, name)
}
