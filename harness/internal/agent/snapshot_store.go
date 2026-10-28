package agent

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"strings"

	"agentsflow/harness/internal/atomicfs"
	"agentsflow/harness/internal/jsonx"
)

const maxSnapshotBytes = 64 << 20

type snapshotStore struct{ root *os.Root }

func openSnapshots(dir string) (*snapshotStore, error) {
	base, err := os.OpenRoot(dir)
	if err != nil {
		return nil, err
	}
	defer base.Close()
	if err := base.Mkdir("snapshots", 0700); err != nil && !os.IsExist(err) {
		return nil, err
	}
	info, err := base.Lstat("snapshots")
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("invalid snapshot directory")
	}
	root, err := base.OpenRoot("snapshots")
	if err != nil {
		return nil, err
	}
	return &snapshotStore{root}, nil
}

func snapshotRef(ref string) bool {
	decoded, err := hex.DecodeString(ref)
	return err == nil && len(decoded) == sha256.Size && ref == strings.ToLower(ref)
}

func (s *snapshotStore) put(value any, token string) (string, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return "", errors.New("cannot encode snapshot")
	}
	data = sanitizeJSONWithToken(data, token)
	if len(data) > maxSnapshotBytes {
		return "", errors.New("snapshot exceeds size limit")
	}
	digest := sha256.Sum256(data)
	ref := hex.EncodeToString(digest[:])
	if old, err := s.read(ref); err == nil && string(old) == string(data) {
		return ref, nil
	}
	if err := atomicfs.Write(s.root, ref+".json", data, 0600); err != nil {
		return "", err
	}
	return ref, nil
}

func (s *snapshotStore) read(ref string) ([]byte, error) {
	if !snapshotRef(ref) {
		return nil, errors.New("invalid snapshot reference")
	}
	f, err := s.root.Open(ref + ".json")
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maxSnapshotBytes+1))
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(data)
	if len(data) > maxSnapshotBytes || hex.EncodeToString(digest[:]) != ref {
		return nil, errors.New("snapshot integrity check failed")
	}
	return data, nil
}

func (s *snapshotStore) get(ref string, target any) error {
	data, err := s.read(ref)
	if err != nil {
		return err
	}
	if jsonx.Unmarshal(data, target) != nil {
		return errors.New("invalid snapshot JSON")
	}
	return nil
}

func (s *snapshotStore) collect(keep ...string) {
	entries, err := fs.ReadDir(s.root.FS(), ".")
	if err != nil {
		return
	}
	for _, entry := range entries {
		ref := strings.TrimSuffix(entry.Name(), ".json")
		if !snapshotRef(ref) || entry.Name() != ref+".json" {
			continue
		}
		retain := false
		for _, current := range keep {
			retain = retain || current == ref
		}
		if !retain {
			_ = s.root.Remove(entry.Name())
		}
	}
}
