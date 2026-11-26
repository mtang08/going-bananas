package coachdashboard

import "testing"

// Digests produced by decision_inputs.digest with Python's UTF-8 canonical JSON.
func TestReceiptDigest(t *testing.T) {
	for _, tc := range []struct{ intent, want string }{
		{"", "7e9d2ef6e3a5a60c2ed5abba0c0d117ee3a7f7d04a5fe2ab592c8a23bb7d9086"},
		{"today_run", "13e6bcaf051a06b9dddf2efc1496478da4add1b2b8def81bd150ee4bb994122a"},
	} {
		got, err := receiptDigest("Café <easy> 🏃\nToday?", tc.intent)
		if err != nil || got != tc.want {
			t.Fatalf("intent %q: got %s (%v), want %s", tc.intent, got, err, tc.want)
		}
	}
}
