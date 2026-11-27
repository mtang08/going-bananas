package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/fitcommand"
	"os"
)

func main() { os.Exit(fitcommand.Main(os.Args[1:])) }
