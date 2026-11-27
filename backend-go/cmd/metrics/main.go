package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/metriccli"
	"os"
)

func main() { os.Exit(metriccli.Main(os.Args[1:])) }
