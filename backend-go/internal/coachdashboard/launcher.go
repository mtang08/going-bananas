package coachdashboard

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

type LocalLauncher struct{ home, workspace, executable string }

func NewLocalLauncher(repoRoot, mode string) (*LocalLauncher, error) {
	switch mode {
	case "real", "demo", "test":
	default:
		return nil, errors.New("unknown coaching mode")
	}
	root, err := filepath.Abs(repoRoot)
	if err != nil {
		return nil, err
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return nil, err
	}
	home := filepath.Join(root, "private", "coach-codex")
	return &LocalLauncher{home: home, workspace: filepath.Join(home, "workspaces", mode), executable: "codex"}, nil
}
func (l *LocalLauncher) Workspace() string { return l.workspace }

func (l *LocalLauncher) prepare() error {
	for _, p := range []string{filepath.Dir(l.home), l.home, filepath.Dir(l.workspace), l.workspace} {
		err := os.Mkdir(p, 0700)
		if err != nil && !os.IsExist(err) {
			return err
		}
		st, err := os.Lstat(p)
		if err != nil {
			return err
		}
		if !st.IsDir() {
			return errors.New("invalid coach directory")
		}
		if p != filepath.Dir(l.home) {
			if err := os.Chmod(p, 0700); err != nil {
				return err
			}
		}
	}
	return nil
}

func (l *LocalLauncher) Open(ctx context.Context) (io.ReadWriteCloser, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if err := l.prepare(); err != nil {
		return nil, &Problem{"turn_failed", "The dashboard could not open its private Codex directory."}
	}
	executable, err := exec.LookPath(l.executable)
	if err != nil {
		return nil, &Problem{"not_installed", "Install the Codex CLI on the machine running Going Bananas."}
	}
	if !filepath.IsAbs(executable) {
		return nil, errors.New("the Codex executable requires an absolute path")
	}
	// Set umask in this child only. Executable and flags are positional arguments.
	args := append([]string{"-c", `umask 077 && exec "$@"`, "going-bananas-coach", executable, "app-server"}, launchFlags...)
	cmd := exec.Command("/bin/sh", args...)
	cmd.Dir = l.workspace
	for _, key := range []string{"HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "TMPDIR"} {
		if v, ok := os.LookupEnv(key); ok {
			cmd.Env = append(cmd.Env, key+"="+v)
		}
	}
	cmd.Env = append(cmd.Env, "CODEX_HOME="+l.home)
	in, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		_ = in.Close()
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		_ = in.Close()
		_ = out.Close()
		return nil, err
	}
	return &processStream{ReadCloser: out, WriteCloser: in, cmd: cmd}, nil
}

type processStream struct {
	io.ReadCloser
	io.WriteCloser
	cmd *exec.Cmd
}

func (s *processStream) Close() error {
	_ = s.WriteCloser.Close()
	_ = s.ReadCloser.Close()
	done := make(chan error, 1)
	go func() { done <- s.cmd.Wait() }()
	timer := time.NewTimer(2 * time.Second)
	defer timer.Stop()
	select {
	case err := <-done:
		return err
	case <-timer.C:
		_ = s.cmd.Process.Kill()
		return <-done
	}
}

var launchFlags = []string{
	"--listen",
	"stdio://",
	"--strict-config",
	"-c",
	"approval_policy=\"never\"",
	"-c",
	"default_permissions=\"going_bananas_coach\"",
	"-c",
	"permissions.going_bananas_coach={filesystem={\":root\"=\"deny\"},network={enabled=false}}",
	"-c",
	"model_provider=\"openai\"",
	"-c",
	"model=\"gpt-6-astra\"",
	"-c",
	"model_reasoning_effort=\"medium\"",
	"-c",
	"forced_login_method=\"chatgpt\"",
	"-c",
	"cli_auth_credentials_store=\"file\"",
	"-c",
	"web_search=\"disabled\"",
	"-c",
	"mcp_servers={}",
	"-c",
	"features.code_mode.direct_only_tool_namespaces=[\"going_bananas\"]",
	"-c",
	"features.code_mode.excluded_tool_namespaces=[\"functions\"]",
	"-c",
	"features.multi_agent_v2={enabled=false,disable_native_tools=true}",
	"-c",
	"tools.experimental_request_user_input.enabled=false",
	"-c",
	"project_doc_max_bytes=0",
	"-c",
	"project_root_markers=[\".going-bananas-coach-project\"]",
	"--disable",
	"shell_tool",
	"--disable",
	"unified_exec",
	"--disable",
	"apps",
	"--disable",
	"plugins",
	"--disable",
	"browser_use",
	"--disable",
	"computer_use",
	"--disable",
	"image_generation",
	"--disable",
	"hooks",
	"--disable",
	"multi_agent",
	"--disable",
	"view_image",
	"--disable",
	"sleep_tool",
	"--disable",
	"goals",
	"--disable",
	"tool_suggest",
	"--enable",
	"skip_host_skill_discovery",
}
