package skills

import (
	"bytes"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"syscall"

	"agentsflow/harness/internal/api"
)

var filenamePattern = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*\.md$`)

func filename(file api.Skill) string {
	if file.Filename != "" {
		return file.Filename
	}
	return file.Name // Compatibility with the documented name-as-filename contract.
}

// Apply reconciles only managed Markdown files and leaves unchanged files untouched.
// The caller must hold its task/sync lock for the entire operation.
func Apply(dir string, files []api.Skill) error {
	wanted := make(map[string][]byte, len(files))
	for _, file := range files {
		name := filename(file)
		if !filenamePattern.MatchString(name) || file.SnapshotContentMissing {
			return errors.New("invalid skill filename or missing snapshot content")
		}
		if _, exists := wanted[name]; exists {
			return errors.New("duplicate skill filename")
		}
		wanted[name] = []byte(file.Content)
	}
	if info, err := os.Lstat(dir); err == nil {
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return errors.New("skills path must be a directory")
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := checkSkillPath(dir, dir); err != nil {
		return err
	}
	project := filepath.Dir(filepath.Dir(dir))
	projectRoot, err := os.OpenRoot(project)
	if err != nil {
		return err
	}
	defer projectRoot.Close()
	rel, err := filepath.Rel(project, dir)
	if err != nil {
		return err
	}
	root, err := openSafeRoot(projectRoot, rel)
	if err != nil {
		return err
	}
	defer root.Close()
	return applyFiles(root, wanted)
}

func applyFiles(root *os.Root, wanted map[string][]byte) error {
	entries, err := fs.ReadDir(root.FS(), ".")
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if filenamePattern.MatchString(entry.Name()) && (entry.Type()&os.ModeSymlink != 0 || !entry.Type().IsRegular()) {
			return errors.New("managed skill must be a regular file")
		}
	}
	for name, data := range wanted {
		info, err := root.Lstat(name)
		if err == nil && (info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular()) {
			return errors.New("managed skill must be a regular file")
		}
		f, err := root.OpenFile(name, os.O_RDONLY|syscall.O_NOFOLLOW, 0)
		var old []byte
		if err == nil {
			old, err = io.ReadAll(f)
			_ = f.Close()
		}
		if err == nil && bytes.Equal(old, data) {
			continue
		}
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		if err := replaceRoot(root, name, data); err != nil {
			return err
		}
	}
	for _, entry := range entries {
		if _, keep := wanted[entry.Name()]; !keep && filenamePattern.MatchString(entry.Name()) {
			if err := root.Remove(entry.Name()); err != nil {
				return err
			}
		}
	}
	return nil
}
