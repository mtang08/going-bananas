package coachdashboard

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"sync/atomic"
	"testing"
	"time"
)

const testAuthURL = "https://auth.openai.com/oauth/authorize?redirect_uri=http%3A%2F%2Flocalhost%3A12345%2Fauth%2Fcallback"

func authPeer(p *peer, signed bool) {
	p.request("initialize", Object{})
	p.request("initialized", nil)
	var account Object
	if signed {
		account = Object{"type": "chatgpt"}
	}
	p.request("account/read", Object{"account": account})
}

func TestAuthStatusCachesWithoutStartingLogin(t *testing.T) {
	rt, _, done := setupPeer(t, func(p *peer) { authPeer(p, false) })
	var count atomic.Int32
	a := NewAuth(func(ctx context.Context) (io.ReadWriteCloser, error) {
		if count.Add(1) > 1 {
			return nil, fmt.Errorf("unexpected process")
		}
		return rt.Open(ctx)
	})
	for range 2 {
		if view := a.Status(t.Context()); view.Status != "signed_out" {
			t.Fatal(view)
		}
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if count.Load() != 1 {
		t.Fatal("expected cached account status")
	}
}

func TestExplicitAuthCompletionAndCancellation(t *testing.T) {
	for _, finish := range []bool{true, false} {
		t.Run(fmt.Sprint(finish), func(t *testing.T) {
			proceed := make(chan struct{})
			rt, _, done := setupPeer(t, func(p *peer) {
				authPeer(p, false)
				p.request("account/login/start", Object{"type": "chatgpt", "loginId": "synthetic", "authUrl": testAuthURL})
				<-proceed
				if finish {
					p.send(Object{"method": "account/login/completed", "params": Object{"loginId": "unrelated", "success": false}})
					p.send(Object{"method": "account/login/completed", "params": Object{"loginId": "synthetic", "success": true}})
				} else {
					q := p.request("account/login/cancel", Object{})
					p.expect(q["loginId"] == "synthetic", "login cancel ID")
				}
			})
			a := NewAuth(rt.Open)
			if v := a.Start(); v.Status != "waiting" {
				t.Fatal(v)
			}
			deadline := time.Now().Add(3 * time.Second)
			for {
				v := a.Status(t.Context())
				if v.URL != nil && *v.URL == testAuthURL {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("expected synthetic login link")
				}
				time.Sleep(time.Millisecond)
			}
			a.turnSignedOut() // A turn that failed during login must preserve the athlete's sign-in link.
			if v := a.Start(); v.URL == nil {
				t.Fatal("duplicate start lost login")
			}
			close(proceed)
			if !finish {
				v, err := a.Cancel(t.Context())
				if err != nil || v.Status != "cancelled" || v.URL != nil {
					t.Fatal(v, err)
				}
			} else {
				for a.Status(t.Context()).Status != "signed_in" {
					if time.Now().After(deadline) {
						t.Fatal("expected signed-in state")
					}
					time.Sleep(time.Millisecond)
				}
			}
			if err := <-done; err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestLoginLinks(t *testing.T) {
	if !validLoginURL(testAuthURL) {
		t.Fatal("rejected synthetic login URL")
	}
	for _, raw := range []string{"http://example.com:1234/auth/callback", "http://localhost/auth/callback", "http://localhost:99999/auth/callback", "http://bad@localhost:1234/auth/callback", "http://localhost:1234/auth/callback?next=foo", "http://127.0.0.1:1234/auth%2fcallback"} {
		if validLoginURL("https://auth.openai.com/oauth/authorize?redirect_uri=" + url.QueryEscape(raw)) {
			t.Fatal(raw)
		}
	}
	for _, raw := range []string{testAuthURL + "#", testAuthURL + "&redirect_uri=another", "https://auth.openai.com.bad/oauth/authorize", testAuthURL + " "} {
		if validLoginURL(raw) {
			t.Fatal(raw)
		}
	}
}

func TestDisconnectedStatusReaderDoesNotCacheFailure(t *testing.T) {
	rt, _, done := setupPeer(t, func(p *peer) { authPeer(p, true) })
	a := NewAuth(func(ctx context.Context) (io.ReadWriteCloser, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		return rt.Open(ctx)
	})
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	_ = a.Status(ctx)
	if status := a.Status(t.Context()); status.Status != "signed_in" {
		t.Fatalf("cancelled refresh persisted %v", status)
	}
	requireOK(t, <-done)
}
