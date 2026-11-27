package googlecalendar

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"golang.org/x/oauth2"
)

type desktopClient struct {
	ID     string `json:"client_id"`
	Secret string `json:"client_secret"`
	Auth   string `json:"auth_uri"`
	Token  string `json:"token_uri"`
}

func readDesktopClient(dir string) (desktopClient, error) {
	var empty desktopClient
	f, err := os.Open(filepath.Join(dir, "google-calendar-client.json"))
	if err != nil {
		return empty, failure("gcal_client_file_missing")
	}
	defer func() { _ = f.Close() }()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return empty, failure("gcal_client_file_missing")
	}
	if info.Mode().Perm()&0077 != 0 {
		return empty, failure("gcal_credential_permissions")
	}
	var config struct{ Installed, Web *desktopClient }
	if json.NewDecoder(f).Decode(&config) != nil {
		return empty, failure("gcal_reauth_required")
	}
	client := config.Installed
	if client == nil {
		client = config.Web
	}
	if client == nil || client.ID == "" || client.Secret == "" {
		return empty, failure("gcal_reauth_required")
	}
	for _, endpoint := range []string{client.Auth, client.Token} {
		u, e := url.Parse(endpoint)
		if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil {
			return empty, failure("gcal_reauth_required")
		}
	}
	return *client, nil
}

// Connect runs installed-app consent and stores credentials compatible with calendar-connect.
// present opens the authorization URL or shows it to the user on the command's diagnostic stream.
func (c *Client) Connect(ctx context.Context, present func(string) error) error {
	app, err := readDesktopClient(c.config.PrivateDir)
	if err != nil {
		return err
	}
	l, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return failure("gcal_remote_error")
	}
	callback := "http://" + l.Addr().String() + "/"
	conf := oauth2.Config{ClientID: app.ID, ClientSecret: app.Secret, RedirectURL: callback, Scopes: []string{readScope}, Endpoint: oauth2.Endpoint{AuthURL: app.Auth, TokenURL: app.Token, AuthStyle: oauth2.AuthStyleInParams}}
	state := rand.Text()
	verifier := oauth2.GenerateVerifier()
	codes := make(chan string, 1)
	srv := http.Server{ReadHeaderTimeout: 5 * time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		if r.Method != http.MethodGet || r.URL.Path != "/" || r.Host != l.Addr().String() || r.URL.Query().Get("state") != state {
			http.Error(w, "Invalid authorization callback.", http.StatusBadRequest)
			return
		}
		code := r.URL.Query().Get("code")
		if r.URL.Query().Get("error") != "" {
			code = ""
		}
		select {
		case codes <- code:
		default:
		}
		_, _ = w.Write([]byte("Authorization response received. You can close this window."))
	})}
	stopped := make(chan struct{})
	go func() { defer close(stopped); _ = srv.Serve(l) }()
	defer func() { _ = srv.Close(); _ = l.Close() }()
	authURL := conf.AuthCodeURL(state, oauth2.AccessTypeOffline, oauth2.SetAuthURLParam("prompt", "consent"), oauth2.S256ChallengeOption(verifier))
	if err := present(authURL); err != nil {
		return failure("gcal_remote_error")
	}
	var code string
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-stopped:
		return failure("gcal_remote_error")
	case code = <-codes:
	}
	if code == "" {
		return failure("gcal_reauth_required")
	}
	token, err := conf.Exchange(context.WithValue(ctx, oauth2.HTTPClient, c.config.HTTPClient), code, oauth2.VerifierOption(verifier))
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		var providerError *oauth2.RetrieveError
		if errors.As(err, &providerError) {
			return failure("gcal_reauth_required")
		}
		return failure("gcal_remote_error")
	}
	if token.RefreshToken == "" {
		return failure("gcal_no_refresh_token")
	}
	if grant, ok := token.Extra("scope").(string); ok && !slices.Contains(strings.Fields(grant), readScope) {
		return failure("gcal_scope_missing")
	}
	data := map[string]any{"token": token.AccessToken, "refresh_token": token.RefreshToken, "client_id": app.ID, "client_secret": app.Secret, "token_uri": app.Token, "scopes": conf.Scopes}
	if !token.Expiry.IsZero() {
		data["expiry"] = token.Expiry.UTC().Format("2006-01-02T15:04:05.000000Z")
	}
	b, err := json.Marshal(data)
	if err != nil {
		return failure("gcal_reauth_required")
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err = writeToken(c.config.PrivateDir, b); err != nil {
		return failure("gcal_credential_permissions")
	}
	return nil
}
