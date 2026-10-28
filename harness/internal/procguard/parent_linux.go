//go:build linux

package procguard

import (
	"errors"
	"io"
	"os"
	"syscall"
)

// The harness alone owns the write end. EOF also detects SIGKILL/crashes of the
// harness, without relying on a polling timer or on inherited process groups.
func watchParent() (<-chan struct{}, func(), error) {
	file := os.NewFile(3, "harness-lifecycle")
	info, err := file.Stat()
	if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
		file.Close()
		return nil, nil, errors.New("missing supervisor lifecycle pipe")
	}
	syscall.CloseOnExec(3)
	done := make(chan struct{})
	go func() { _, _ = io.Copy(io.Discard, file); close(done) }()
	return done, func() { _ = file.Close() }, nil
}
