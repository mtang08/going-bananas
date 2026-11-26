// Package metrics implements identities and calculations for stored training metrics.
package metrics

import (
	"crypto/sha256"
	"encoding/hex"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

// CompletionAssociation is the input shared by metric source references and
// coaching freshness. Assessment results can change without changing this link.
type CompletionAssociation struct {
	SessionUID         uuid.UUID
	ActivityID         *uuid.UUID
	StrongWorkoutID    *uuid.UUID
	ManualSessionID    *uuid.UUID
	MatchMethod        string
	ModificationReason *string
	ReasonNote         *string
	InputVersion       int
}

// Hash reproduces Python's completion_association_hash for a persisted completion.
func (c CompletionAssociation) Hash() (string, error) {
	encoded, err := canonicaljson.Metric(map[string]any{
		"session_uid":         c.SessionUID,
		"activity_id":         c.ActivityID,
		"strong_workout_id":   c.StrongWorkoutID,
		"manual_session_id":   c.ManualSessionID,
		"match_method":        c.MatchMethod,
		"modification_reason": c.ModificationReason,
		"reason_note":         c.ReasonNote,
		"input_version":       c.InputVersion,
	})
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}
