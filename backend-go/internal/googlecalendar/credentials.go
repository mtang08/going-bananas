package googlecalendar

import (
	"context"
	"encoding/json"
	"errors"
	"math/rand/v2"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"
)

type credentials struct {
	expiresAt      time.Time
	Token          string `json:"token"`
	RefreshToken   string `json:"refresh_token"`
	ClientID       string `json:"client_id"`
	ClientSecret   string `json:"client_secret"`
	Expiry         string `json:"expiry"`
	QuotaProjectID string `json:"quota_project_id"`
	RaptToken      string `json:"rapt_token"`
}

func (c *Client) authorize(ctx context.Context) (credentials, error) {
	return c.authorizeAfter(ctx, "")
}

// On a 401, refresh only if another caller has not already replaced the rejected bearer.
func (c *Client) authorizeAfter(ctx context.Context, rejected string) (credentials, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	var creds credentials
	if !c.Connected() {
		return creds, failure("gcal_not_connected")
	}
	p := filepath.Join(c.config.PrivateDir, tokenFile)
	st, err := os.Stat(p)
	if err != nil {
		return creds, failure("gcal_reauth_required")
	}
	if st.Mode().Perm()&0077 != 0 {
		return creds, failure("gcal_credential_permissions")
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return creds, failure("gcal_reauth_required")
	}
	var data map[string]json.RawMessage
	if json.Unmarshal(b, &data) != nil || json.Unmarshal(b, &creds) != nil {
		return creds, failure("gcal_reauth_required")
	}
	for _, key := range []string{"refresh_token", "client_id", "client_secret"} {
		if _, ok := data[key]; !ok {
			return creds, failure("gcal_reauth_required")
		}
	}
	var expiry time.Time
	if creds.Expiry != "" {
		// google-auth reads its authorized-user cache at second precision.
		s, _, _ := strings.Cut(strings.TrimRight(creds.Expiry, "Z"), ".")
		expiry, err = time.Parse("2006-01-02T15:04:05", s)
		if err != nil {
			return creds, failure("gcal_reauth_required")
		}
	}
	scopes := []string{}
	raw := data["scopes"]
	if raw != nil && json.Unmarshal(raw, &scopes) != nil {
		var text string
		if json.Unmarshal(raw, &text) != nil {
			return creds, failure("gcal_reauth_required")
		}
		scopes = strings.Fields(text)
	}
	if !slices.Contains(scopes, readScope) {
		return creds, failure("gcal_scope_missing")
	}
	creds.expiresAt = expiry
	if creds.Token != "" && creds.Token != rejected && c.config.Now().Before(expiry.Add(-225*time.Second)) {
		return creds, nil
	}
	if err := c.refresh(ctx, &creds, data, scopes); err != nil {
		return creds, err
	}
	return creds, nil
}

func (c *Client) refresh(ctx context.Context, v *credentials, data map[string]json.RawMessage, scopes []string) error {
	if v.RefreshToken == "" || v.ClientID == "" || v.ClientSecret == "" {
		return failure("gcal_reauth_required")
	}
	form := url.Values{"grant_type": {"refresh_token"}, "refresh_token": {v.RefreshToken}, "client_id": {v.ClientID}, "client_secret": {v.ClientSecret}, "scope": {strings.Join(scopes, " ")}}
	if v.RaptToken != "" {
		form.Set("rapt", v.RaptToken)
	}
	body, status, err := c.fetchGrant(ctx, form)
	if err != nil {
		return err
	}
	var grant struct {
		AccessToken  string      `json:"access_token"`
		RefreshToken string      `json:"refresh_token"`
		Scope        string      `json:"scope"`
		ExpiresIn    json.Number `json:"expires_in"`
	}
	if status != 200 || json.Unmarshal(body, &grant) != nil || grant.AccessToken == "" {
		return failure("gcal_reauth_required")
	}
	if grant.Scope != "" && !slices.Contains(strings.Fields(grant.Scope), readScope) {
		return failure("gcal_scope_missing")
	}
	put := func(key, s string) { data[key], _ = json.Marshal(s) }
	put("token", grant.AccessToken)
	put("token_uri", tokenURL)
	if grant.RefreshToken != "" {
		put("refresh_token", grant.RefreshToken)
	}
	if grant.ExpiresIn != "" {
		seconds, err := strconv.ParseInt(grant.ExpiresIn.String(), 10, 32)
		if err != nil {
			return failure("gcal_reauth_required")
		}
		v.expiresAt = c.config.Now().UTC().Add(time.Duration(seconds) * time.Second)
		put("expiry", v.expiresAt.Format("2006-01-02T15:04:05.000000Z"))
	} else {
		delete(data, "expiry")
		v.expiresAt = time.Time{}
	}
	b, err := json.Marshal(data)
	if err != nil {
		return failure("gcal_reauth_required")
	}
	if err := writeToken(c.config.PrivateDir, b); err != nil {
		return failure("gcal_credential_permissions")
	}
	v.Token = grant.AccessToken
	return nil
}

func writeToken(dir string, b []byte) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".gcal-")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(f.Name()) }()
	_, err = f.Write(b)
	if err == nil {
		err = f.Sync()
	}
	err = errors.Join(err, f.Close())
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), filepath.Join(dir, tokenFile))
}

func retryGrant(status int, body []byte) bool {
	switch status {
	case 408, 429, 500, 503, 504:
		return true
	}
	var reason struct {
		Error       string
		Description string `json:"error_description"`
	}
	if json.Unmarshal(body, &reason) != nil {
		return false
	}
	for _, s := range []string{reason.Error, reason.Description} {
		switch s {
		case "internal_failure", "server_error", "temporarily_unavailable":
			return true
		}
	}
	return false
}

func (c *Client) fetchGrant(ctx context.Context, form url.Values) ([]byte, int, error) {
	for attempt := 0; ; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.config.TokenURL, strings.NewReader(form.Encode()))
		if err != nil {
			return nil, 0, failure("gcal_remote_error")
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		body, _, status, err := request(c, req)
		if err != nil || status == 200 || attempt == 2 || !retryGrant(status, body) {
			return body, status, err
		}
		// Match google-auth's three attempts and exponential delay with 10% jitter.
		wait := time.Duration(float64(time.Second) * (0.9 + rand.Float64()*0.2) * float64(1+attempt))
		select {
		case <-ctx.Done():
			return nil, 0, ctx.Err()
		case <-time.After(wait):
		}
	}
}
