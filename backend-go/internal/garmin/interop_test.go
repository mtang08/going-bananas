package garmin

import (
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
	"testing"
	"time"
)

// GARMIN_SDK_PYTHON selects an interpreter with the pinned Python SDK installed.
// Both clients share a temporary cache and one loopback-only token issuer.
func TestPythonSDKCacheInterop(t *testing.T) {
	python := os.Getenv("GARMIN_SDK_PYTHON")
	if python == "" {
		t.Skip("set GARMIN_SDK_PYTHON to the backend Python interpreter")
	}
	f := setup(t, func(http.ResponseWriter, *http.Request) { t.Error("unexpected data request") })
	t.Setenv("NO_PROXY", "*")
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	f.config.CacheFile = dir + "/bearer.json"
	pythonObtain := func() {
		t.Helper()
		cmd := exec.CommandContext(t.Context(), python, "-c", `import sys
from importlib.metadata import version
from garmin_personal_api import PersonalApiAuthenticator
assert version("garmin-connect-personal-api-python") == "1.0.0"
with PersonalApiAuthenticator(bearer_token_cache_file=sys.argv[1]) as auth:
    assert auth.obtain_token("synthetic").expires_at == 4102444800
`, f.config.CacheFile)
		if output, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("Python SDK: %v: %s", err, output)
		}
	}
	pythonObtain()
	if f.exchanges.Load() != 1 {
		t.Fatal("Python did not seed cache")
	}
	if f.open(t).token != token(1) || f.exchanges.Load() != 1 {
		t.Fatal("Go did not reuse Python token")
	}
	if err := os.Remove(f.config.CacheFile); err != nil {
		t.Fatal(err)
	}
	if f.open(t).token != token(2) || f.exchanges.Load() != 2 {
		t.Fatal("Go did not write cache")
	}
	pythonObtain()
	if f.exchanges.Load() != 2 {
		t.Fatal("Python did not reuse Go token")
	}
	// Both clients use the cache timestamp and the same one-hour renewal window.
	for i, seconds := range []int64{-1, 1800} {
		b, err := os.ReadFile(f.config.CacheFile)
		if err != nil {
			t.Fatal(err)
		}
		var cache tokenEntry
		if err := json.Unmarshal(b, &cache); err != nil {
			t.Fatal(err)
		}
		cache.ExpiresAt = float64(time.Now().Unix() + seconds)
		b, err = json.Marshal(cache)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(f.config.CacheFile, b, 0600); err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			pythonObtain()
		} else {
			f.open(t)
		}
		if f.exchanges.Load() != int32(3+i) {
			t.Fatal("expected renewal")
		}
	}
}
