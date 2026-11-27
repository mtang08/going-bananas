package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/strongcli"
	"os"
)

func main() { os.Exit(strongcli.Standalone(os.Args[1:])) }
