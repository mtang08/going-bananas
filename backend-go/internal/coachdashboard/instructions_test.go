package coachdashboard

import (
	"os"
	"path/filepath"
	"testing"
)

func TestInstructionPathsRejectSymlinks(t *testing.T) {
	const skill = ".codex/skills/going-bananas-coach"
	for _, rel := range []string{".codex", ".codex/skills", skill, skill + "/SKILL.md", skill + "/references", skill + "/references/coaching-workflows.md", skill + "/references/proposal-format.md"} {
		t.Run(rel, func(t *testing.T) {
			root := t.TempDir()
			if err := os.MkdirAll(filepath.Join(root, skill, "references"), 0700); err != nil {
				t.Fatal(err)
			}
			for _, name := range []string{"SKILL.md", "references/coaching-workflows.md", "references/proposal-format.md"} {
				if err := os.WriteFile(filepath.Join(root, skill, name), []byte("fixture"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := LoadInstructions(root); err != nil {
				t.Fatal(err)
			}
			original := filepath.Join(root, rel)
			target := original + ".redirect"
			if err := os.Rename(original, target); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(filepath.Base(target), original); err != nil {
				t.Fatal(err)
			}
			if _, err := LoadInstructions(root); err == nil {
				t.Fatal("accepted redirected path")
			}
		})
	}
}
