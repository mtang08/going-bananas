package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/backupcli"
	"os"
)

func main() { os.Exit(backupcli.Main(os.Args[1:])) }
