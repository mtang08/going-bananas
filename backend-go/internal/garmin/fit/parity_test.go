package fit

import (
	"encoding/json"
	"os"
	"reflect"
	"runtime/debug"
	"strings"
	"testing"
)

// Generated from decode_fit_zip. Both implementations receive the exact same ZIP bytes.
func TestNormalizedParity(t *testing.T) {
	data, err := os.ReadFile("testdata/normalized.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name    string
		Archive []byte
		Error   string
		Decoded map[string]any
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	nativeVersion := linkedFITVersion(t)
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			result, err := DecodeZIP(tc.Archive)
			if tc.Error != "" {
				if err == nil || err.Error() != tc.Error || result != nil {
					t.Fatalf("want nil and %s, got result present=%t and %v", tc.Error, result != nil, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(result)
			if err != nil {
				t.Fatal(err)
			}
			for _, canary := range []string{"position_lat", "position_long", "serial_number", "123456789", "987654321", "synthetic-device-canary"} {
				if strings.Contains(string(encoded), canary) {
					t.Fatalf("normalized output contains excluded field or value %q", canary)
				}
			}
			var got map[string]any
			if err := json.Unmarshal(encoded, &got); err != nil {
				t.Fatal(err)
			}
			if tc.Decoded["sdk_version"] != "21.221.0" {
				t.Fatalf("unexpected reference SDK version %v", tc.Decoded["sdk_version"])
			}
			tc.Decoded["sdk_version"] = nativeVersion
			for field, want := range tc.Decoded {
				if actual, ok := got[field]; !ok || !reflect.DeepEqual(actual, want) {
					t.Errorf("%s differs from decode_fit_zip: got %v, want %v", field, actual, want)
				}
			}
			for field := range got {
				if _, ok := tc.Decoded[field]; !ok {
					t.Errorf("unexpected output field %s", field)
				}
			}
		})
	}
}

func linkedFITVersion(t *testing.T) string {
	t.Helper()
	info, ok := debug.ReadBuildInfo()
	if !ok {
		t.Fatal("missing Go build information")
	}
	for _, dep := range info.Deps {
		if dep.Path == "github.com/muktihari/fit" {
			if dep.Replace != nil {
				dep = dep.Replace
			}
			return dep.Path + " " + dep.Version
		}
	}
	t.Fatal("FIT decoder missing from Go build information")
	return ""
}
