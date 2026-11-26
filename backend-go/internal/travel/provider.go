package travel

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// Provider supplies already-authorized primary-calendar pages to Sync.
type Provider interface {
	Connected() bool
	Fetch(context.Context, Window) ([]json.RawMessage, error)
}

type ProviderError struct{ Code string }

func (e *ProviderError) Error() string { return e.Code }
func (e *ProviderError) Status() int {
	switch e.Code {
	case "gcal_not_connected", "gcal_credential_permissions", "gcal_reauth_required", "gcal_scope_missing":
		return 409
	case "gcal_rate_limited":
		return 503
	default:
		return 502
	}
}
func (e *ProviderError) Message() string {
	switch e.Code {
	case "gcal_not_connected":
		return "Google Calendar is not connected. Run calendar-connect."
	case "gcal_credential_permissions":
		return "Google Calendar files must not be readable by other users."
	case "gcal_reauth_required":
		return "Google Calendar access expired or was revoked. Run calendar-connect again."
	case "gcal_scope_missing":
		return "Google Calendar read access was not granted. Run calendar-connect again."
	case "gcal_rate_limited":
		return "Google Calendar is rate limiting requests. Try again shortly."
	case "gcal_invalid_response":
		return "Google Calendar returned an unexpected response."
	default:
		return "Google Calendar request failed."
	}
}

// Sync shares the Python calendar fetch lock. No transaction remains open during
// network I/O. Reconciliation uses the same home zone and bounds as the fetch.
func Sync(ctx context.Context, pool *pgxpool.Pool, privateDir string, provider Provider, now time.Time) (Result, error) {
	if provider == nil || !provider.Connected() {
		return Result{}, &ProviderError{"gcal_not_connected"}
	}
	if privateDir == "" {
		return Result{}, errors.New("missing calendar lock directory")
	}
	lock, err := os.OpenFile(filepath.Join(privateDir, ".google-calendar-sync.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return Result{}, err
	}
	defer func() { _ = lock.Close() }()
	for {
		err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if err == nil {
			break
		}
		if !errors.Is(err, syscall.EWOULDBLOCK) {
			return Result{}, err
		}
		select {
		case <-ctx.Done():
			return Result{}, ctx.Err()
		case <-time.After(50 * time.Millisecond):
		}
	}
	zone, err := db.New(pool).CalendarTimezone(ctx)
	if err != nil {
		return Result{}, err
	}
	home, err := time.LoadLocation(zone)
	if err != nil {
		return Result{}, err
	}
	pages, err := provider.Fetch(ctx, SyncWindow(now, home))
	if err != nil {
		if ctx.Err() != nil {
			return Result{}, ctx.Err()
		}
		var source *ProviderError
		if !errors.As(err, &source) {
			source = &ProviderError{"gcal_remote_error"}
		}
		if err := RecordFailure(ctx, pool, now, source.Code); err != nil {
			return Result{}, err
		}
		return Result{}, source
	}
	result, err := applyWindow(ctx, pool, Delivery{Now: now, Pages: pages}, home)
	if errors.Is(err, ErrInvalidResponse) {
		return Result{}, &ProviderError{"gcal_invalid_response"}
	}
	return result, err
}
