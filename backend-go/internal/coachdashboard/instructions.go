package coachdashboard

import (
	_ "embed"
	"errors"
	"io"
	"os"
	"strings"
	"syscall"
	"unicode/utf8"
)

//go:embed protocol/dashboard.md
var dashboardInstructions string

// Open one named directory relative to a pinned parent. Verify identity after
// opening so a concurrent replacement cannot redirect the trusted skill path.
func instructionDir(parent *os.Root, name string) (*os.Root, error) {
	info, err := parent.Lstat(name)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() {
		return nil, errors.New("expected instruction directory")
	}
	sub, err := parent.OpenRoot(name)
	if err != nil {
		return nil, err
	}
	actual, err := sub.Stat(".")
	if err != nil || !os.SameFile(info, actual) {
		_ = sub.Close()
		return nil, errors.New("instruction directory changed")
	}
	return sub, nil
}

func instructionFile(dir *os.Root, name string) (string, error) {
	before, err := dir.Lstat(name)
	if err != nil || !before.Mode().IsRegular() {
		return "", errors.New("invalid coaching instruction file")
	}
	file, err := dir.OpenFile(name, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return "", err
	}
	defer func() { _ = file.Close() }()
	info, err := file.Stat()
	if err != nil || !os.SameFile(before, info) {
		return "", errors.New("invalid coaching instruction file")
	}
	data, err := io.ReadAll(file)
	if err != nil || !utf8.Valid(data) {
		return "", errors.New("unreadable coaching instruction file")
	}
	return strings.ReplaceAll(strings.ReplaceAll(string(data), "\r\n", "\n"), "\r", "\n"), nil
}

func LoadInstructions(repoRoot string) (string, error) {
	problem := &Problem{"turn_failed", "The dashboard could not load its coaching instructions."}
	dir, err := os.OpenRoot(repoRoot)
	if err != nil {
		return "", problem
	}
	defer func() { _ = dir.Close() }()
	for _, name := range []string{".codex", "skills", "going-bananas-coach"} {
		child, err := instructionDir(dir, name)
		if err != nil {
			return "", problem
		}
		_ = dir.Close()
		dir = child
	}
	skill, err := instructionFile(dir, "SKILL.md")
	if err != nil {
		return "", problem
	}
	refs, err := instructionDir(dir, "references")
	if err != nil {
		return "", problem
	}
	defer func() { _ = refs.Close() }()
	parts := []string{strings.TrimSpace(dashboardInstructions), skill}
	for _, name := range []string{"coaching-workflows.md", "proposal-format.md"} {
		s, err := instructionFile(refs, name)
		if err != nil {
			return "", problem
		}
		parts = append(parts, s)
	}
	return strings.Join(parts, "\n\n"), nil
}
