// Package checkins stores check-in observations, immutable phone receipts and revision history.
package checkins

import (
	"encoding/binary"
	"time"

	"github.com/google/uuid"
)

const FirstStepsKey = "phone-first-steps:"

type Symptom struct {
	ID       *uuid.UUID `json:"id,omitempty"`
	Site     string     `json:"site"`
	Side     string     `json:"side"`
	Severity float64    `json:"severity"`
	Timing   string     `json:"timing"`
}

type Input struct {
	IdempotencyKey string     `json:"idempotency_key"`
	Kind           string     `json:"kind"`
	ObservedAt     time.Time  `json:"observed_at"`
	Fatigue        *float64   `json:"fatigue"`
	Illness        *string    `json:"illness"`
	GaitChange     *string    `json:"gait_change"`
	PainReported   *bool      `json:"pain_reported"`
	ContextTags    []string   `json:"context_tags"`
	ActivityID     *uuid.UUID `json:"activity_id"`
	PromptID       *uuid.UUID `json:"prompt_id"`
	Note           *string    `json:"note"`
	Symptoms       []Symptom  `json:"symptoms"`
}

type View struct {
	ID             uuid.UUID  `json:"id"`
	IdempotencyKey string     `json:"idempotency_key"`
	Version        int        `json:"version"`
	Kind           string     `json:"kind"`
	ObservedAt     string     `json:"observed_at"`
	RecordedAt     string     `json:"recorded_at"`
	Fatigue        *float64   `json:"fatigue"`
	Illness        *string    `json:"illness"`
	GaitChange     *string    `json:"gait_change"`
	PainReported   *bool      `json:"pain_reported"`
	ContextTags    []string   `json:"context_tags"`
	ActivityID     *uuid.UUID `json:"activity_id"`
	PromptID       *uuid.UUID `json:"prompt_id"`
	Note           *string    `json:"note"`
	SchemaVersion  int        `json:"schema_version"`
	Symptoms       []Symptom  `json:"symptoms"`
}

type DomainError struct {
	Status        int
	Code, Message string
}

func (e *DomainError) Error() string                 { return e.Code }
func problem(code, message string, status int) error { return &DomainError{status, code, message} }

func wireInstant(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond()/1000 != 0 {
		layout += ".000000"
	}
	return t.UTC().Format(layout + "-07:00")
}
func symptomID(checkin uuid.UUID, ordinal int) uuid.UUID {
	id := checkin
	binary.BigEndian.PutUint16(id[:2], uint16(ordinal))
	return id
}
