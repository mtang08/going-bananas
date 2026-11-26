package providerjobs

import (
	"context"
	"errors"
	"math"
	"math/rand/v2"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

func retryDelay(err error, attempt int, now time.Time) (time.Duration, bool) {
	var remote *garmin.RemoteError
	var network net.Error
	switch {
	case errors.As(err, &remote):
		switch remote.StatusCode {
		case 429, 500, 502, 503, 504:
		default:
			return 0, false
		}
		after := strings.TrimSpace(remote.RetryAfter)
		if secs, e := strconv.ParseFloat(after, 64); e == nil && !math.IsNaN(secs) && !math.IsInf(secs, 0) {
			return time.Duration(min(max(secs, 0), float64(math.MaxInt64/time.Second)) * float64(time.Second)), true
		}
		if at, e := http.ParseTime(after); e == nil {
			return max(0, at.Sub(now)), true
		}
	case errors.As(err, &network), err.Error() == "garmin_transport_error":
		// The HTTP client redacts transport errors that could include signed URLs.
	default:
		return 0, false
	}
	seconds := math.Min(300, math.Pow(2, float64(attempt))+rand.Float64())
	return time.Duration(seconds * float64(time.Second)), true
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func failureCode(err error) string {
	var remote *garmin.RemoteError
	if errors.As(err, &remote) && (remote.StatusCode == 401 || remote.StatusCode == 403) {
		return "credential_attention"
	}
	switch err.Error() {
	case "unsupported_dataset", "repeated_activity_page", "activity_page_limit", "mixed_source_account":
		return err.Error()
	default:
		return "remote_or_import_error"
	}
}
