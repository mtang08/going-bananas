// Command phone-gateway serves the existing phone assets behind Tailscale Serve.
package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/phonegateway"
)

func run() error {
	demo := flag.Bool("demo", false, "use the dedicated demo origin and API")
	assets := flag.String("assets", "frontend/public/phone", "phone asset directory")
	flag.Parse()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	data, err := exec.CommandContext(ctx, "tailscale", "status", "--json").Output()
	if err != nil {
		return fmt.Errorf("could not read Tailscale status: %w", err)
	}
	access, err := phonegateway.Discover(data, *demo)
	if err != nil {
		return err
	}
	l, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", access.ListenPort))
	if err != nil {
		return err
	}
	defer func() { _ = l.Close() }()
	fmt.Printf("Phone gateway (%s): https://%s/phone/\nListening on %s.\n", access.Mode, access.Host, l.Addr())
	s := http.Server{Handler: phonegateway.Gateway{Access: access, Assets: os.DirFS(*assets)}, ReadTimeout: 15 * time.Second, ReadHeaderTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second}
	return s.Serve(l)
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
