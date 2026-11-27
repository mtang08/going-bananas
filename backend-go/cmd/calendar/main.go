package main

import (
	"github.com/mtang08/going-bananas/backend-go/internal/calendarcli"
	"os"
)

func main() { os.Exit(calendarcli.Main(os.Args[1:])) }
