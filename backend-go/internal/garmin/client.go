// Package garmin reads the Garmin Personal API and shares the Python SDK's bearer cache.
package garmin

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const tokenPath = "/personalapitoken-service/personal-api/personal-api-key/token"

type Config struct {
	KeyFile string
	// Open creates a missing cache directory with mode 0700. An existing
	// parent directory must already deny group and other access.
	CacheFile string
	Timeout   time.Duration
}

type Client struct {
	base, key, cacheFile, fingerprint string
	http                              *http.Client
	mu                                sync.Mutex
	token                             string
}

type RemoteError struct {
	StatusCode int
	RetryAfter string
}

func (e *RemoteError) Error() string { return fmt.Sprintf("garmin_http_%d", e.StatusCode) }

func apiKey(keyFile string) (string, error) {
	key := os.Getenv("GARMIN_API_KEY")
	if key == "" {
		key = os.Getenv("GARMIN_PERSONAL_API_KEY")
	}
	if key == "" {
		f, err := os.Open(keyFile)
		if err != nil {
			return "", errors.New("garmin_key_file_missing")
		}
		defer func() { _ = f.Close() }()
		info, err := f.Stat()
		if err != nil || !info.Mode().IsRegular() {
			return "", errors.New("garmin_key_file_missing")
		}
		if info.Mode().Perm()&0077 != 0 {
			return "", errors.New("garmin_key_file_permissions")
		}
		b, err := io.ReadAll(f)
		if err != nil {
			return "", err
		}
		key = string(b)
	}
	key = strings.TrimSpace(key)
	if key == "" {
		return "", errors.New("garmin_key_file_empty")
	}
	return key, nil
}

func Open(ctx context.Context, cfg Config) (*Client, error) {
	key, err := apiKey(cfg.KeyFile)
	if err != nil {
		return nil, err
	}
	if cfg.Timeout < 0 {
		return nil, errors.New("timeout must be greater than zero")
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 30 * time.Second
	}
	base := strings.TrimRight(os.Getenv("GARMIN_PERSONAL_API_BASE_URL"), "/")
	if base == "" {
		base = "https://personal.connectapi.garmin.com"
	}
	dir := filepath.Dir(cfg.CacheFile)
	if dir == "." || cfg.CacheFile == "" {
		return nil, errors.New("dedicated cache directory required")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("garmin_cache_directory_permissions")
	}
	c := &Client{
		base: base, key: key, cacheFile: cfg.CacheFile,
		fingerprint: fmt.Sprintf("%x", sha256.Sum256([]byte(base+"\x00"+key))),
		http:        &http.Client{Timeout: cfg.Timeout, CheckRedirect: redirect},
	}
	var entry tokenEntry
	b, err := os.ReadFile(cfg.CacheFile)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	if err == nil && json.Unmarshal(b, &entry) == nil && entry.Fingerprint == c.fingerprint && entry.Token != "" && entry.ExpiresAt-float64(time.Now().UnixNano())/1e9 > 3600 {
		if err := os.Chmod(cfg.CacheFile, 0600); err != nil {
			return nil, err
		}
		c.token = entry.Token
		return c, nil
	}
	if err := c.exchange(ctx); err != nil {
		return nil, err
	}
	return c, nil
}

// requests strips credentials whenever a redirect changes hosts. Go's
// default redirect handling also forwards them to subdomains.
func redirect(req *http.Request, via []*http.Request) error {
	if len(via) >= 10 {
		return errors.New("too many redirects")
	}
	previous := via[len(via)-1].URL
	if previous.Scheme == "https" && req.URL.Scheme != "https" {
		return errors.New("insecure Garmin redirect")
	}
	if via[len(via)-1].Header.Get("Authorization") == "" || previous.Host != req.URL.Host || previous.Scheme != req.URL.Scheme {
		req.Header.Del("Authorization")
	}
	return nil
}

type tokenEntry struct {
	Fingerprint string  `json:"fingerprint"`
	Token       string  `json:"access_token"`
	ExpiresAt   float64 `json:"expires_at"`
}

func expiration(token string) (float64, error) {
	var claims struct {
		Exp json.Number `json:"exp"`
	}
	parts := strings.Split(token, ".")
	if len(parts) >= 2 {
		payload, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(parts[1], "="))
		if err == nil && json.Unmarshal(payload, &claims) == nil {
			if exp, err := strconv.ParseFloat(claims.Exp.String(), 64); err == nil {
				return exp, nil
			}
		}
	}
	return 0, errors.New("invalid_garmin_token_expiration")
}

func (c *Client) exchange(ctx context.Context) error {
	body, err := c.request(ctx, http.MethodPost, tokenPath, nil, "*/*", "ApiKey "+c.key)
	if err != nil {
		return err
	}
	token := strings.TrimSpace(string(body))
	exp, err := expiration(token)
	if err != nil {
		return err
	}
	// Readers in either runtime always see one complete cache entry.
	f, err := os.CreateTemp(filepath.Dir(c.cacheFile), ".bearer-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(f.Name()) }()
	err = json.NewEncoder(f).Encode(tokenEntry{c.fingerprint, token, exp})
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err := os.Rename(f.Name(), c.cacheFile); err != nil {
		return err
	}
	c.token = token
	return nil
}

func (c *Client) request(ctx context.Context, method, path string, query url.Values, accept, auth string) ([]byte, error) {
	target := c.base + path
	if len(query) > 0 {
		target += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, target, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", accept)
	req.Header.Set("Authorization", auth)
	res, err := c.http.Do(req)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return nil, context.Canceled
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, context.DeadlineExceeded
		}
		// Transport errors can contain signed redirect URLs.
		return nil, errors.New("garmin_transport_error")
	}
	defer func() { _ = res.Body.Close() }()
	if res.StatusCode >= 400 {
		return nil, &RemoteError{res.StatusCode, res.Header.Get("Retry-After")}
	}
	return io.ReadAll(res.Body)
}

func (c *Client) refresh(ctx context.Context, previous string) (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if previous == c.token {
		if err := c.exchange(ctx); err != nil {
			return "", err
		}
	}
	return c.token, nil
}

func (c *Client) get(ctx context.Context, path string, q url.Values, accept string) ([]byte, error) {
	c.mu.Lock()
	token := c.token
	c.mu.Unlock()
	body, err := c.request(ctx, http.MethodGet, path, q, accept, "Bearer "+token)
	var remote *RemoteError
	if !errors.As(err, &remote) || remote.StatusCode != 401 {
		return body, err
	}
	token, err = c.refresh(ctx, token)
	if err != nil {
		return nil, err
	}
	return c.request(ctx, http.MethodGet, path, q, accept, "Bearer "+token)
}
