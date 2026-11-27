package garmincli

import (
	"testing"
)

func TestOpenRequiresRealModeAndRefreshBeforeCredentials(t *testing.T) {
	for mode, want := range map[string]string{"real": "garmin_refresh_required", "demo": "real_mode_required"} {
		_, err := Open(t.Context(), mode, Config{})
		if err == nil || err.Error() != want {
			t.Fatalf("mode %q: %v", mode, err)
		}
	}
}
