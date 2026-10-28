package config

import (
	"crypto/sha256"
	"os"
)

// ChangedError requires a restart; retrying cannot refresh the loaded snapshot.
type ChangedError struct{}

func (*ChangedError) Error() string { return "config changed, restart harness" }

// CheckUnchanged rejects stale runtime configuration without echoing its contents.
func (c Config) CheckUnchanged() error {
	if c.sourcePath == "" {
		return nil // Programmatically constructed configurations have no source file.
	}
	data, err := os.ReadFile(c.sourcePath)
	if err != nil || sha256.Sum256(data) != c.sourceHash {
		return &ChangedError{}
	}
	return nil
}
