package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/workercommand"
	"os"
)

func main() { os.Exit(workercommand.Main(os.Args[1:])) }
