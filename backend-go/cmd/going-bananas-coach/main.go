package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/coachcli"
	"os"
)

func main() { os.Exit(coachcli.Main(os.Args[1:])) }
