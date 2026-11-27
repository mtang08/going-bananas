package main

import (
	"testing"

	"github.com/mtang08/going-bananas/backend-go/api"
)

func TestModeAndDatabaseMustMatch(t *testing.T) {
	t.Setenv("GOING_BANANAS_BACKEND", "")
	for _, tc := range []struct {
		mode    api.AppMode
		dsn     string
		allowed bool
	}{
		{api.Test, "postgresql+psycopg://localhost/gb_fixture_test", true},
		{api.Demo, "postgresql://localhost/garmin_demo", true},
		{api.Real, "postgresql://localhost/garmin_real", false},
		{api.Test, "postgresql://localhost/garmin_real", false},
		{api.Demo, "postgresql://localhost/garmin_test", false},
		{api.Test, "", false},
	} {
		cfg, err := runtimeConfig(tc.mode, tc.dsn)
		if (err == nil) != tc.allowed {
			t.Errorf("%q %q: %v", tc.mode, tc.dsn, err)
		}
		if err == nil && cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] != "on" {
			t.Error("database default must be read-only")
		}
	}
}

func TestRealServerRequiresAnExplicitSwitch(t *testing.T) {
	t.Setenv("GOING_BANANAS_BACKEND", "go")
	if _, err := runtimeConfig(api.Real, "postgresql://localhost/fixture_real"); err != nil {
		t.Fatal(err)
	}
	if _, err := runtimeConfig(api.Real, "postgresql://localhost/fixture_demo"); err == nil {
		t.Fatal("accepted mismatched database")
	}
}

func TestExternalListenerRejected(t *testing.T) {
	if err := serve([]string{"-listen", "0.0.0.0:0"}); err == nil || err.Error() != "listen address must be 127.0.0.1 with a numeric port" {
		t.Fatal(err)
	}
}
