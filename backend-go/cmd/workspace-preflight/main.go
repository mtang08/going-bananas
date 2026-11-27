// Command workspace-preflight verifies a quiesced workspace before cutover.
package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/preflight"
	"os"
)

func main() { os.Exit(preflight.Main(os.Args[1:])) }
