// Package googlecalendar fetches primary-calendar events with the authorized-user
// credentials written by calendar-connect.
package googlecalendar

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

const (
	tokenFile   = "google-calendar-token.json"
	readScope   = "https://www.googleapis.com/auth/calendar.readonly"
	eventsURL   = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
	tokenURL    = "https://oauth2.googleapis.com/token"
	fetchFields = "nextPageToken,items(id,status,eventType,summary,location,start,end,transparency,updated,attendees(self,responseStatus))"
)

type Config struct {
	PrivateDir          string
	EventsURL, TokenURL string
	HTTPClient          *http.Client
	Now                 func() time.Time
}

type Client struct {
	config Config
	mu     sync.Mutex
}

var _ travel.Provider = (*Client)(nil)

func New(privateDir string) *Client { return NewWithConfig(Config{PrivateDir: privateDir}) }

func NewWithConfig(cfg Config) *Client {
	if cfg.EventsURL == "" {
		cfg.EventsURL = eventsURL
	}
	if cfg.TokenURL == "" {
		cfg.TokenURL = tokenURL
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	client := http.Client{}
	if cfg.HTTPClient != nil {
		client = *cfg.HTTPClient
	}
	if client.Timeout == 0 {
		client.Timeout = 30 * time.Second
	}
	// Credentials belong only to the configured endpoints.
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	cfg.HTTPClient = &client
	return &Client{config: cfg}
}

func (c *Client) Connected() bool {
	if c.config.PrivateDir == "" {
		return false
	}
	st, err := os.Stat(filepath.Join(c.config.PrivateDir, tokenFile))
	return err == nil && st.Mode().IsRegular()
}

func failure(code string) error { return &travel.ProviderError{Code: code} }

// RemoteError keeps transport diagnostics safe to inspect without retaining the body.
type RemoteError struct {
	Cause      *travel.ProviderError
	StatusCode int
	RetryAfter string
}

func (e *RemoteError) Error() string { return e.Cause.Code }
func (e *RemoteError) Unwrap() error { return e.Cause }

func request(c *Client, req *http.Request) ([]byte, http.Header, int, error) {
	resp, err := c.config.HTTPClient.Do(req)
	if err != nil {
		if req.Context().Err() != nil {
			return nil, nil, 0, req.Context().Err()
		}
		return nil, nil, 0, failure("gcal_remote_error")
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, 0, failure("gcal_remote_error")
	}
	return body, resp.Header, resp.StatusCode, nil
}

func calendarError(body []byte, headers http.Header, status int) error {
	code := "gcal_remote_error"
	switch status {
	case http.StatusUnauthorized:
		code = "gcal_reauth_required"
	case http.StatusTooManyRequests:
		code = "gcal_rate_limited"
	case http.StatusForbidden:
		var v struct {
			Error struct{ Errors []struct{ Reason string } }
		}
		if json.Unmarshal(body, &v) == nil && len(v.Error.Errors) > 0 {
			switch v.Error.Errors[0].Reason {
			case "rateLimitExceeded", "userRateLimitExceeded":
				code = "gcal_rate_limited"
			}
		}
	}
	return &RemoteError{Cause: &travel.ProviderError{Code: code}, StatusCode: status, RetryAfter: headers.Get("Retry-After")}
}

type eventPage struct {
	Items        []json.RawMessage `json:"items"`
	Next         string            `json:"nextPageToken,omitempty"`
	RequestToken string            `json:"page_token,omitempty"`
}

func pageBody(body []byte, token string) (eventPage, error) {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(body, &obj); err != nil || obj == nil {
		return eventPage{}, failure("gcal_invalid_response")
	}
	page := eventPage{Items: []json.RawMessage{}, RequestToken: token}
	if raw, ok := obj["nextPageToken"]; ok && json.Unmarshal(raw, &page.Next) != nil {
		return page, failure("gcal_invalid_response")
	}
	if raw, ok := obj["items"]; ok {
		if err := json.Unmarshal(raw, &page.Items); err != nil || page.Items == nil {
			return page, failure("gcal_invalid_response")
		}
		for _, item := range page.Items {
			if b := bytes.TrimSpace(item); len(b) == 0 || b[0] != '{' {
				return page, failure("gcal_invalid_response")
			}
		}
	}
	return page, nil
}

func calendarTime(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond()/1000 != 0 {
		layout += ".000000"
	}
	return t.Format(layout + "-07:00")
}

func (c *Client) Fetch(ctx context.Context, w travel.Window) ([]json.RawMessage, error) {
	creds, err := c.authorize(ctx)
	if err != nil {
		return nil, err
	}
	u, err := url.Parse(c.config.EventsURL)
	if err != nil {
		return nil, failure("gcal_remote_error")
	}
	q := url.Values{"singleEvents": {"true"}, "orderBy": {"startTime"}, "showDeleted": {"false"}, "maxResults": {"2500"}, "fields": {fetchFields}, "timeMin": {calendarTime(w.From)}, "timeMax": {calendarTime(w.Until)}}
	var pages []json.RawMessage
	seen := map[string]bool{}
	for len(pages) < 20 {
		if len(pages) > 0 && !creds.expiresAt.IsZero() && !c.config.Now().Before(creds.expiresAt.Add(-225*time.Second)) {
			creds, err = c.authorize(ctx)
			if err != nil {
				return nil, err
			}
		}
		u.RawQuery = q.Encode()
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
		if err != nil {
			return nil, failure("gcal_remote_error")
		}
		req.Header.Set("Authorization", "Bearer "+creds.Token)
		if creds.QuotaProjectID != "" {
			req.Header.Set("x-goog-user-project", creds.QuotaProjectID)
		}
		body, headers, status, err := request(c, req)
		if err != nil {
			return nil, err
		}
		if status != 200 {
			return nil, calendarError(body, headers, status)
		}
		page, err := pageBody(body, q.Get("pageToken"))
		if err != nil {
			return nil, err
		}
		data, err := json.Marshal(page)
		if err != nil {
			return nil, failure("gcal_invalid_response")
		}
		pages = append(pages, data)
		if page.Next == "" {
			return pages, nil
		}
		if seen[page.Next] {
			return nil, failure("gcal_invalid_response")
		}
		seen[page.Next] = true
		q.Set("pageToken", page.Next)
	}
	return nil, failure("gcal_invalid_response")
}
