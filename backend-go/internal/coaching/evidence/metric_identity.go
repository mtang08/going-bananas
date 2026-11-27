package evidence

import (
	"encoding/json"
	"sync"
)

type metricIdentity struct {
	Method string `json:"method_version"`
	Hash   string `json:"config_hash"`
	Metric string `json:"metric_id"`
}

var registeredMetrics = sync.OnceValue(func() map[string]metricIdentity {
	var identities []metricIdentity
	if err := json.Unmarshal(metricIdentities, &identities); err != nil {
		panic(err)
	}
	byID := make(map[string]metricIdentity, len(identities))
	for _, entry := range identities {
		byID[entry.Metric] = entry
	}
	return byID
})

// RegisteredMetric returns the method and config selected by the coaching evidence manifest.
func RegisteredMetric(id string) (method, hash string, ok bool) {
	entry, ok := registeredMetrics()[id]
	return entry.Method, entry.Hash, ok
}
