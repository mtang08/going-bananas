package travelhttp

import "github.com/mtang08/going-bananas/backend-go/internal/httpinput"

func inputDate(v any) (string, string) { return httpinput.Date(v) }
