// Package loginstartup manages the macOS login preference for the configured checkout.
package loginstartup

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	"howett.net/plist"
)

const label = "com.local.going-bananas.dashboard"

type State struct {
	Status  string  `json:"status"`
	Enabled *bool   `json:"enabled"`
	Message *string `json:"message"`
}

func problem(status, msg string) State { return State{Status: status, Message: &msg} }
func unavailable(msg string) State     { return problem("unavailable", msg) }

type agent struct {
	root, home, domain string
	command            func(context.Context, string, string) (string, bool, error)
}

// Local uses the checkout supplied by the server and the current account's registered home directory.
func Local(root, mode string) Handler {
	return Handler{Mode: mode, Run: func(ctx context.Context, want *bool) State {
		if runtime.GOOS != "darwin" {
			return problem("unsupported", "Login startup is available on macOS.")
		}
		if mode != "real" {
			return problem("unsupported", "Open the configured real dashboard to change login startup.")
		}
		if os.Getuid() == 0 {
			return problem("unsupported", "Login startup requires a macOS user session.")
		}
		u, err := user.LookupId(strconv.Itoa(os.Getuid()))
		resolved, rootErr := filepath.EvalSymlinks(root)
		if err != nil || rootErr != nil || !filepath.IsAbs(resolved) {
			return unavailable(updateFailed)
		}
		ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
		defer cancel()
		return (agent{resolved, u.HomeDir, "gui/" + u.Uid, launchctl}).run(ctx, want)
	}}
}

const updateFailed = "macOS could not update login startup. Try again."

func launchctl(ctx context.Context, action, target string) (string, bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/launchctl", action, target)
	cmd.Env = []string{"LC_ALL=C"}
	data, err := cmd.Output()
	var exit *exec.ExitError
	if ctx.Err() != nil {
		return "", false, ctx.Err()
	}
	if errors.As(err, &exit) {
		return string(data), false, nil
	}
	return string(data), err == nil, err
}
func (a agent) dir() string  { return filepath.Join(a.home, "Library", "LaunchAgents") }
func (a agent) path() string { return filepath.Join(a.dir(), label+".plist") }
func (a agent) ready() bool {
	for _, path := range []string{".env", "frontend/dist/index.html"} {
		f, err := os.Stat(filepath.Join(a.root, path))
		if err != nil || !f.Mode().IsRegular() {
			return false
		}
	}
	return true
}
func (a agent) args() []string {
	python := "/usr/bin/python3"
	for _, dir := range filepath.SplitList(a.searchPath()) {
		p := filepath.Join(dir, "python3")
		if f, err := os.Stat(p); err == nil && f.Mode().IsRegular() && f.Mode()&0111 != 0 {
			python = p
			break
		}
	}
	return []string{"/bin/bash", filepath.Join(a.root, "scripts/run"), python, filepath.Join(a.root, "scripts/dashboard-login.py"), "serve"}
}
func (a agent) searchPath() string {
	return strings.Join([]string{"/opt/homebrew/opt/postgresql@17/bin", "/opt/homebrew/bin", "/usr/local/bin", filepath.Join(a.home, ".local/bin"), "/usr/bin", "/bin", "/usr/sbin", "/sbin"}, ":")
}
func (a agent) installed() (map[string]any, *State) {
	var job map[string]any
	f, err := os.OpenFile(a.path(), os.O_RDONLY|syscall.O_NOFOLLOW, 0)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	failure := unavailable("The existing Going Bananas login agent could not be read.")
	if errors.Is(err, syscall.ELOOP) {
		failure = unavailable("The existing Going Bananas login item is a symbolic link. Check it before changing startup.")
	}
	if err != nil {
		return nil, &failure
	}
	defer func() { _ = f.Close() }()
	var raw any
	if err := plist.NewDecoder(f).Decode(&raw); err != nil {
		return nil, &failure
	}
	job, _ = raw.(map[string]any)
	args, ok := job["ProgramArguments"].([]any)
	malformed := unavailable("The existing Going Bananas login item is malformed. Check it before changing startup.")
	if job["Label"] != label || !ok || len(args) != 5 {
		return nil, &malformed
	}
	for _, v := range args {
		if _, ok := v.(string); !ok {
			return nil, &malformed
		}
	}
	command := a.args()
	if args[0] != command[0] || args[1] != command[1] || args[3] != command[3] || args[4] != command[4] || job["WorkingDirectory"] != a.root {
		s := problem("other_checkout", "A login agent already points to another Going Bananas checkout. Manage it there.")
		return nil, &s
	}
	return job, nil
}
func (a agent) inspect(ctx context.Context) (s State, starts, disabled bool) {
	job, bad := a.installed()
	if bad != nil {
		return *bad, false, false
	}
	output, ok, err := a.command(ctx, "print-disabled", a.domain)
	if err != nil {
		return unavailable(updateFailed), false, false
	}
	if !ok {
		return unavailable("macOS could not read login startup. Open Going Bananas from your Mac desktop session."), false, false
	}
	for line := range strings.SplitSeq(output, "\n") {
		name, state, found := strings.Cut(line, "=>")
		if !found || strings.Trim(strings.TrimSpace(name), "\"") != label {
			continue
		}
		switch strings.TrimRight(strings.TrimSpace(state), ",;") {
		case "disabled", "true":
			disabled = true
		case "enabled", "false":
		default:
			return unavailable("macOS returned an unreadable login startup status."), false, false
		}
		break
	}
	if job == nil {
		_, running, err := a.command(ctx, "print", a.domain+"/"+label)
		if err != nil {
			return unavailable(updateFailed), false, false
		}
		if running {
			return unavailable("A Going Bananas login agent is registered but its settings file is missing. Sign out and in to reset it."), false, false
		}
		if !a.ready() {
			return unavailable("Finish local setup and build Going Bananas before enabling login startup."), false, false
		}
	}
	starts = job["RunAtLoad"] == true && job["Disabled"] != true
	on := starts && !disabled
	status := "disabled"
	if on {
		status = "enabled"
	}
	return State{Status: status, Enabled: &on}, starts, disabled
}
func (a agent) write() error {
	log := filepath.Join(a.root, "private/dashboard-launch.log")
	job := map[string]any{"Label": label, "ProgramArguments": a.args(), "WorkingDirectory": a.root, "EnvironmentVariables": map[string]string{"PATH": a.searchPath()}, "RunAtLoad": true, "StandardOutPath": log, "StandardErrorPath": log}
	f, err := os.CreateTemp(a.dir(), ".login-*.plist")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(f.Name()) }()
	err = plist.NewEncoder(f).Encode(job)
	if err == nil {
		err = f.Sync()
	}
	err = errors.Join(err, f.Close())
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), a.path())
}
func (a agent) change(ctx context.Context, want bool) State {
	before, starts, disabled := a.inspect(ctx)
	if before.Enabled == nil || *before.Enabled == want {
		return before
	}
	if want {
		if !a.ready() {
			return unavailable("Finish local database setup and build the app before launching this checkout.")
		}
		if err := os.MkdirAll(filepath.Join(a.root, "private"), 0700); err != nil {
			return unavailable(updateFailed)
		}
	}
	if !want || disabled {
		action := "disable"
		if want {
			action = "enable"
		}
		_, ok, err := a.command(ctx, action, a.domain+"/"+label)
		if err != nil {
			return unavailable(updateFailed)
		}
		if !ok {
			return unavailable(fmt.Sprintf("macOS could not %s the Going Bananas login agent.", action))
		}
	}
	if want && !starts {
		if err := a.write(); err != nil {
			return unavailable(updateFailed)
		}
	}
	after, _, _ := a.inspect(ctx)
	if after.Enabled == nil {
		return after
	}
	if *after.Enabled != want {
		return unavailable("macOS did not confirm the login startup setting. Try again.")
	}
	return after
}
func (a agent) run(ctx context.Context, want *bool) State {
	before, _, _ := a.inspect(ctx)
	if want == nil || before.Enabled == nil || *before.Enabled == *want {
		return before
	}
	// Resolve existing ancestors before creating any missing directories.
	base := a.dir()
	for {
		_, err := os.Lstat(base)
		if !errors.Is(err, os.ErrNotExist) {
			break
		}
		base = filepath.Dir(base)
	}
	real, err := filepath.EvalSymlinks(base)
	home, homeErr := filepath.EvalSymlinks(a.home)
	if err != nil || homeErr != nil {
		return unavailable(updateFailed)
	}
	rel, err := filepath.Rel(home, real)
	if err != nil || rel != "." && !filepath.IsLocal(rel) {
		return unavailable("The LaunchAgents directory points outside the macOS user's home.")
	}
	if err := os.MkdirAll(a.dir(), 0700); err != nil {
		return unavailable(updateFailed)
	}
	lock, err := os.OpenFile(filepath.Join(a.dir(), "."+label+".lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return unavailable(updateFailed)
	}
	defer func() { _ = lock.Close() }()
	for {
		err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if err == nil {
			break
		}
		if !errors.Is(err, syscall.EWOULDBLOCK) {
			return unavailable(updateFailed)
		}
		select {
		case <-ctx.Done():
			return unavailable(updateFailed)
		case <-time.After(20 * time.Millisecond):
		}
	}
	return a.change(ctx, *want)
}
