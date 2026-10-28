package skills

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

func openSafeRoot(base *os.Root, rel string) (*os.Root, error) {
	current, owned := base, false
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		if part == "" || part == "." {
			continue
		}
		if err := makeDirectory(current, part); err != nil {
			if owned {
				_ = current.Close()
			}
			return nil, err
		}
		next, err := current.OpenRoot(part)
		if owned {
			_ = current.Close()
		}
		if err != nil {
			return nil, err
		}
		current, owned = next, true
	}
	return current, nil
}

func makeDirectory(root *os.Root, name string) error {
	if err := root.Mkdir(name, 0755); err != nil && !os.IsExist(err) {
		return err
	}
	info, err := root.Lstat(name)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("skills path cannot contain symlinks")
	}
	return nil
}

func checkSkillPath(root, path string) error {
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	project, err := filepath.Abs(filepath.Dir(filepath.Dir(root)))
	if err != nil {
		return err
	}
	projectReal, err := filepath.EvalSymlinks(project)
	if err != nil {
		return errors.New("skills project root is not canonical")
	}
	rel, err := filepath.Rel(projectReal, abs)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return errors.New("skills path escapes project")
	}
	current := projectReal
	for _, component := range strings.Split(rel, string(filepath.Separator)) {
		if component == "." || component == "" {
			continue
		}
		current = filepath.Join(current, component)
		info, err := os.Lstat(current)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("skills path cannot contain symlinks")
		}
		resolved, err := filepath.EvalSymlinks(current)
		if err != nil || resolved != current {
			return errors.New("skills path is not canonical")
		}
	}
	return nil
}
