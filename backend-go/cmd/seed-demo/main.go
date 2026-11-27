// Command seed-demo builds the synthetic demo dashboard in the configured demo workspace.
package main

import (
	"context"
	"fmt"
	"os"

	"github.com/mtang08/going-bananas/backend-go/internal/demoseed"
)

func main() {
	if err := demoseed.Run(context.Background(), os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
