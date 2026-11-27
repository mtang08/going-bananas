package calendarcli

import (
	"io"
	"testing"
)

func TestModeAndDayWindowBeforeCredentialLookup(t *testing.T) {
	for _, tc := range []struct {
		mode string
		args []string
		want string
	}{{"demo", []string{"calendar-connect", "--no-browser"}, "real_mode_required"}, {"test", []string{"calendar-probe"}, "real_mode_required"}, {"real", []string{"calendar-probe", "--days", "181"}, "invalid_date_window"}, {"real", []string{"calendar-probe"}, "gcal_not_connected"}, {"real", []string{"calendar-connect", "--no-browser"}, "gcal_client_file_missing"}} {
		if err := run(t.Context(), tc.mode, t.TempDir(), tc.args, io.Discard, io.Discard); err == nil || err.Error() != tc.want {
			t.Fatalf("%v: %v", tc.args, err)
		}
	}
}
