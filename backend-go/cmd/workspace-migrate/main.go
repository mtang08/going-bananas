package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/migratecli"
	"os"
)

func main() { os.Exit(migratecli.Main(os.Args[1:])) }
