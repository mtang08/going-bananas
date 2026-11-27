package main

import (
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLaunchFromSyntheticTailscaleStatus(t *testing.T) {
	directory := t.TempDir()
	shim := `#!/bin/sh
[ "$1" = status ] && [ "$2" = --json ] || exit 1
echo '{"BackendState":"Running","Self":{"DNSName":"fixture.ts.net.","UserID":42},"User":{"42":{"LoginName":"owner"}}}'
`
	if err := os.WriteFile(filepath.Join(directory, "tailscale"), []byte(shim), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "index.html"), []byte("synthetic shell"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", directory)
	for _, tc := range []struct{ mode, bind, origin string }{{"real", "127.0.0.1:8765", "fixture.ts.net:8443"}, {"demo", "127.0.0.1:8766", "fixture.ts.net:8444"}} {
		t.Run(tc.mode, func(t *testing.T) {
			listener, err := net.Listen("tcp4", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = listener.Close() }()
			args := []string{"-assets", directory}
			if tc.mode == "demo" {
				args = append(args, "-demo")
			}
			done := make(chan error, 1)
			go func() {
				done <- run(args, func(network, address string) (net.Listener, error) {
					if network != "tcp4" || address != tc.bind {
						return nil, errors.New("wrong gateway bind address")
					}
					return listener, nil
				})
			}()
			req, err := http.NewRequestWithContext(t.Context(), http.MethodGet, "http://"+listener.Addr().String()+"/phone/", nil)
			if err != nil {
				t.Fatal(err)
			}
			req.Host = tc.origin
			req.Header.Set("Tailscale-User-Login", "owner")
			client := http.Client{Timeout: 5 * time.Second}
			result, err := client.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			data, err := io.ReadAll(result.Body)
			_ = result.Body.Close()
			if err != nil || result.StatusCode != 200 || string(data) != "synthetic shell" {
				t.Fatalf("status %d, body %q, err %v", result.StatusCode, data, err)
			}
			_ = listener.Close()
			if err := <-done; !errors.Is(err, net.ErrClosed) {
				t.Fatalf("unexpected server exit: %v", err)
			}
		})
	}
}
