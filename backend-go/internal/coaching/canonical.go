// Package coaching computes identities for coaching decision evidence.
package coaching

import "github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"

// CanonicalJSON returns the bytes used by Python to fingerprint coaching evidence.
// Supply civil dates as ISO strings and preserve JSON numbers with Decoder.UseNumber.
func CanonicalJSON(value any) ([]byte, error) {
	return canonicaljson.Coaching(value)
}
