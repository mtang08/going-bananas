package loginstartup

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"howett.net/plist"
)

func readReference(t *testing.T, path string, target any) {
	t.Helper()
	data, err := os.ReadFile("testdata/" + path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, target); err != nil {
		t.Fatal(err)
	}
}
func writeFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}
func mkdir(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(path, 0700); err != nil {
		t.Fatal(err)
	}
}
func TestLaunchAgentTransitions(t *testing.T) {
	var sequence []struct {
		Action    *bool
		Change    string
		Result    State
		Calls     []string
		Rewritten bool
	}
	readReference(t, "reference.json", &sequence)
	a := agent{root: t.TempDir(), home: t.TempDir(), domain: "gui/4321"}
	mkdir(t, filepath.Join(a.root, "frontend/dist"))
	writeFile(t, filepath.Join(a.root, "frontend/dist/index.html"), nil)
	writeFile(t, filepath.Join(a.root, ".env"), nil)
	var registered, disabled, ignore, offline bool
	var calls []string
	a.command = func(_ context.Context, action, target string) (string, bool, error) {
		calls = append(calls, action)
		if action == "print-disabled" {
			if target != a.domain {
				t.Fatal(target)
			}
			return fmt.Sprintf("%q => %t", label, disabled), !offline, nil
		}
		if target != a.domain+"/"+label {
			t.Fatal(target)
		}
		switch action {
		case "print":
			return "", registered, nil
		case "disable", "enable":
			if !ignore {
				disabled = action == "disable"
			}
			return "", true, nil
		default:
			t.Fatalf("unexpected launchctl command %s", action)
			return "", false, nil
		}
	}
	for i, step := range sequence {
		switch step.Change {
		case "registered":
			registered = true
		case "ignore-enable":
			ignore = true
			disabled = true
		case "repair", "binary", "foreign":
			job, err := a.installed()
			if err != nil {
				t.Fatal(err)
			}
			if step.Change == "repair" {
				ignore = false
				job["Disabled"] = true
			}
			if step.Change == "foreign" {
				job["WorkingDirectory"] = filepath.Join(a.root, "elsewhere")
			}
			raw, e := plist.Marshal(job, plist.BinaryFormat)
			if e != nil {
				t.Fatal(e)
			}
			writeFile(t, a.path(), raw)
		case "malformed":
			writeFile(t, a.path(), []byte("not a plist"))
		case "missing":
			if err := os.Remove(a.path()); err != nil {
				t.Fatal(err)
			}
		case "offline":
			offline = true
		case "symlink":
			if err := os.Symlink(filepath.Join(a.home, "absent"), a.path()); err != nil {
				t.Fatal(err)
			}
		}
		before, _ := os.ReadFile(a.path())
		calls = []string{}
		got := a.run(t.Context(), step.Action)
		after, _ := os.ReadFile(a.path())
		if !reflect.DeepEqual(got, step.Result) || !reflect.DeepEqual(calls, step.Calls) || (string(after) != string(before)) != step.Rewritten {
			b, _ := json.Marshal(got)
			t.Fatalf("step %d %s got %s, calls %v, rewritten %t; expected %+v", i, step.Change, b, calls, string(after) != string(before), step)
		}
		if step.Rewritten {
			job, bad := a.installed()
			if bad != nil {
				t.Fatal(bad)
			}
			f, e := os.Stat(a.path())
			if e != nil || f.Mode().Perm() != 0600 || job["StandardOutPath"] != filepath.Join(a.root, "private/dashboard-launch.log") || job["RunAtLoad"] != true {
				t.Fatal("incorrect agent plist")
			}
		}
	}
}

func TestRefusesEscapingDirectoryAndSymlinkLock(t *testing.T) {
	for _, kind := range []string{"directory", "lock"} {
		t.Run(kind, func(t *testing.T) {
			a := agent{root: t.TempDir(), home: t.TempDir(), domain: "gui/123", command: func(_ context.Context, action, _ string) (string, bool, error) {
				switch action {
				case "print-disabled":
					return "", true, nil
				case "print":
					return "", false, nil
				default:
					t.Fatalf("unexpected mutation %s", action)
					return "", false, nil
				}
			}}
			mkdir(t, filepath.Join(a.root, "frontend/dist"))
			writeFile(t, filepath.Join(a.root, "frontend/dist/index.html"), nil)
			writeFile(t, filepath.Join(a.root, ".env"), nil)
			outside := t.TempDir()
			if kind == "directory" {
				if err := os.Symlink(outside, filepath.Join(a.home, "Library")); err != nil {
					t.Fatal(err)
				}
			} else {
				mkdir(t, a.dir())
				if err := os.Symlink(filepath.Join(outside, "target"), filepath.Join(a.dir(), "."+label+".lock")); err != nil {
					t.Fatal(err)
				}
			}
			on := true
			if got := a.run(t.Context(), &on); got.Status != "unavailable" {
				t.Fatal(got)
			}
			entries, err := os.ReadDir(outside)
			if err != nil || len(entries) != 0 {
				t.Fatal("wrote outside synthetic LaunchAgents directory")
			}
		})
	}
}

func TestDemoNeverRunsLaunchctl(t *testing.T) {
	on := true
	state := Local(t.TempDir(), "demo").Run(t.Context(), &on)
	if state.Status != "unsupported" || state.Enabled != nil {
		t.Fatal(state)
	}
}
