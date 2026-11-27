package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/exportcommand"
	"os"
)

func main() { os.Exit(exportcommand.Main(os.Args[1:])) }
