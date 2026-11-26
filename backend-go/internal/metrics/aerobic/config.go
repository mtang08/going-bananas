package aerobic

import (
	_ "embed"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

//go:embed config.json
var rawConfig []byte
var Config = func() map[string]any {
	val, err := metrics.JSONValue(rawConfig)
	if err != nil {
		panic(err)
	}
	return val.(map[string]any)
}()

const ID = "aerobic_efficiency"
const Version = "v1"
