package coachdashboard

import (
	"context"
	"errors"
	"io"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
)

type AuthView struct {
	Status string   `json:"status"`
	URL    *string  `json:"url"`
	Error  *Problem `json:"error"`
}

type Auth struct {
	open     func(context.Context) (io.ReadWriteCloser, error)
	mu       sync.Mutex
	statusMu sync.Mutex
	view     AuthView
	checked  time.Time
	cancel   context.CancelFunc
	done     chan struct{}
	epoch    uint64
}

func NewAuth(open func(context.Context) (io.ReadWriteCloser, error)) *Auth {
	return &Auth{open: open, view: AuthView{Status: "idle"}}
}

// A rejected turn supersedes any cached or in-flight account read. An explicit
// login owns its own status until it finishes or the athlete cancels it.
func (a *Auth) turnSignedOut() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.view.Status == "waiting" {
		return
	}
	a.epoch++
	a.view = AuthView{Status: "signed_out"}
	a.checked = time.Now()
}

func (a *Auth) session(ctx context.Context) (*RPC, error) {
	stream, err := a.open(ctx)
	if err != nil {
		return nil, err
	}
	return OpenRPC(ctx, stream)
}

func authAccount(ctx context.Context, r *RPC) (bool, error) {
	result, err := r.Request(ctx, "account/read", Object{"refreshToken": false})
	return field(object(result["account"]), "type") == "chatgpt", err
}

func (a *Auth) Status(ctx context.Context) AuthView {
	a.statusMu.Lock()
	defer a.statusMu.Unlock()
	a.mu.Lock()
	view, epoch := a.view, a.epoch
	refresh := (view.Status == "idle" || view.Status == "signed_in" || view.Status == "signed_out") && time.Since(a.checked) >= 30*time.Second
	a.mu.Unlock()
	if !refresh {
		return view
	}
	r, err := a.session(ctx)
	var signed bool
	if err == nil {
		signed, err = authAccount(ctx, r)
		r.Close()
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.epoch == epoch && ctx.Err() == nil {
		switch {
		case err != nil:
			a.view = authFailure(err)
		case signed:
			a.view = AuthView{Status: "signed_in"}
		default:
			a.view = AuthView{Status: "signed_out"}
		}
		a.checked = time.Now()
	}
	return a.view
}

func authFailure(err error) AuthView {
	var p *Problem
	if !errors.As(err, &p) {
		p = &Problem{"turn_failed", "The dashboard could not complete this request. Try again."}
	}
	if errors.Is(err, context.DeadlineExceeded) {
		p = &Problem{"timeout", "The ChatGPT sign-in link expired. Start sign-in again."}
	}
	return AuthView{Status: "failed", Error: p}
}

func (a *Auth) Start() AuthView {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.done != nil || a.view.Status == "signed_in" {
		return a.view
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	a.epoch++
	a.cancel = cancel
	a.done = make(chan struct{})
	a.view = AuthView{Status: "waiting"}
	go a.login(ctx, cancel)
	return a.view
}

func (a *Auth) login(ctx context.Context, cancel context.CancelFunc) {
	defer cancel()
	err := a.runLogin(ctx)
	a.mu.Lock()
	defer a.mu.Unlock()
	switch {
	case errors.Is(ctx.Err(), context.Canceled):
		a.view = AuthView{Status: "cancelled"}
	case err != nil:
		a.view = authFailure(err)
	default:
		a.view = AuthView{Status: "signed_in"}
		a.checked = time.Now()
	}
	a.epoch++
	close(a.done)
	a.done = nil
	a.cancel = nil
}

func (a *Auth) Cancel(ctx context.Context) (AuthView, error) {
	a.mu.Lock()
	done := a.done
	if done != nil {
		a.cancel()
	}
	a.mu.Unlock()
	if done != nil {
		select {
		case <-ctx.Done():
			return AuthView{}, ctx.Err()
		case <-done:
		}
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.view, nil
}

func (a *Auth) runLogin(ctx context.Context) error {
	r, err := a.session(ctx)
	if err != nil {
		return err
	}
	defer r.Close()
	signed, err := authAccount(ctx, r)
	if err != nil || signed {
		return err
	}
	login, err := r.Request(ctx, "account/login/start", Object{"type": "chatgpt", "useHostedLoginSuccessPage": true, "appBrand": "codex"})
	if err != nil {
		return err
	}
	id := field(login, "loginId")
	if id == "" || field(login, "type") != "chatgpt" {
		return &Problem{"auth_required", "Codex could not start ChatGPT sign-in. Try again."}
	}
	complete := false
	defer func() {
		if !complete {
			cleanup, stop := context.WithTimeout(context.Background(), 3*time.Second)
			defer stop()
			_, _ = r.Request(cleanup, "account/login/cancel", Object{"loginId": id})
		}
	}()
	link := field(login, "authUrl")
	if !validLoginURL(link) {
		return &Problem{"auth_required", "Codex returned an invalid ChatGPT sign-in link. Try again."}
	}
	a.mu.Lock()
	a.view.URL = &link
	a.mu.Unlock()
	for {
		event, err := r.Event(ctx)
		if err != nil {
			return err
		}
		if _, ok := event["id"]; ok {
			if err := reject(ctx, r, event); err != nil {
				return err
			}
			continue
		}
		data := object(event["params"])
		if field(event, "method") == "account/login/completed" && field(data, "loginId") == id {
			complete = true
			if data["success"] != true {
				return &Problem{"auth_required", "ChatGPT sign-in did not finish. Try again."}
			}
			return nil
		}
	}
}

func validLoginURL(value string) bool {
	if strings.IndexFunc(value, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) != -1 || strings.Contains(value, "#") {
		return false
	}
	u, err := url.Parse(value)
	if err != nil || u.Scheme != "https" || u.Host != "auth.openai.com" || u.User != nil || u.EscapedPath() != "/oauth/authorize" {
		return false
	}
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil || len(q["redirect_uri"]) != 1 {
		return false
	}
	raw := q.Get("redirect_uri")
	redirect, err := url.Parse(raw)
	if err != nil || redirect.Scheme != "http" || redirect.User != nil || redirect.EscapedPath() != "/auth/callback" || strings.ContainsAny(raw, "?#") {
		return false
	}
	host := redirect.Hostname()
	port, err := strconv.Atoi(redirect.Port())
	return (host == "127.0.0.1" || host == "localhost") && err == nil && port > 0 && port <= 65535
}
