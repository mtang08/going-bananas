// Package calendar owns calendar completion writes and their transaction boundaries.
package calendar

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type ReportStatus string

const (
	CompletedAsPlanned ReportStatus = "completed_as_planned"
	Skipped            ReportStatus = "skipped"
	Unknown            ReportStatus = "unknown"
)

// SelfReport applies to requests without a recording. Unknown can undo a prior mark.
type SelfReport struct {
	ExpectedVersion    int
	Status             ReportStatus
	ModificationReason *string
	ReasonNote         *string
}

type Problem struct {
	Code    string
	Message string
}

func (p *Problem) Error() string { return p.Message }

type CompletionChange struct {
	SessionUID           uuid.UUID
	Before, After        *db.SessionCompletion
	PlanDay              pgtype.Date
	PreviousRecordingDay pgtype.Date
}

type RefreshCompletion func(context.Context, pgx.Tx, CompletionChange) error

// SaveSelfReport holds the same writer lock as Python until both the source write
// and its derived refresh commit. The result describes the source mutation before rematching.
func SaveSelfReport(ctx context.Context, pool *pgxpool.Pool, uid uuid.UUID, input SelfReport, now time.Time, refresh RefreshCompletion) (CompletionChange, error) {
	if refresh == nil {
		return CompletionChange{}, errors.New("completion refresh is required")
	}
	var change CompletionChange
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		head, err := q.LockCalendarHead(ctx)
		if err != nil {
			return err
		}
		var changed bool
		change, changed, err = applySelfReport(ctx, q, uid, input, now, head)
		if err != nil || !changed {
			return err
		}
		if _, err := q.BumpDataRevision(ctx); err != nil {
			return err
		}
		return refresh(ctx, tx, change)
	})
	if err != nil {
		return CompletionChange{}, err
	}
	return change, nil
}

func (s SelfReport) validate() error {
	switch s.Status {
	case Skipped, Unknown, CompletedAsPlanned:
	default:
		return &Problem{"invalid_completion", "Invalid self-reported outcome"}
	}
	if s.ModificationReason != nil {
		switch *s.ModificationReason {
		case "symptom_onset", "fatigue", "illness", "schedule", "weather", "equipment", "other":
		default:
			return &Problem{"invalid_completion", "Invalid modification reason"}
		}
	}
	return nil
}

func textValue(v *string) pgtype.Text {
	if v == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *v, Valid: true}
}

func hasRecording(row *db.SessionCompletion) bool {
	return row != nil && (row.ActivityID.Valid || row.ManualSessionID.Valid || row.StrongWorkoutID.Valid)
}

func applySelfReport(ctx context.Context, q *db.Queries, uid uuid.UUID, input SelfReport, now time.Time, head int32) (CompletionChange, bool, error) {
	change := CompletionChange{SessionUID: uid}
	if err := input.validate(); err != nil {
		return change, false, err
	}
	id := pgtype.UUID{Bytes: uid, Valid: true}
	old, err := q.CompletionForSession(ctx, id)
	if err == nil {
		change.Before = &old
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return change, false, err
	}
	if input.ExpectedVersion != int(old.Version) {
		return change, false, &Problem{"version_conflict", "Completion changed; reload before editing"}
	}

	plan, err := q.CompletionPlanAtHead(ctx, db.CompletionPlanAtHeadParams{SessionUid: id, CalendarVersionNumber: head})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return change, false, err
	}
	change.PlanDay = plan.LocalDate

	// A recording's current athlete-local date can differ from its stored import date.
	linked := hasRecording(change.Before)
	if input.Status == CompletedAsPlanned || linked {
		zone, err := q.CalendarTimezone(ctx)
		if err != nil {
			return change, false, err
		}
		if input.Status == CompletedAsPlanned {
			loc, err := time.LoadLocation(zone)
			if err != nil {
				return change, false, err
			}
			year, month, day := now.In(loc).Date()
			today := time.Date(year, month, day, 0, 0, 0, 0, time.UTC)
			if !plan.LocalDate.Valid || plan.Deleted || plan.Kind == "rest" || plan.LocalDate.Time.After(today) {
				return change, false, &Problem{"invalid_completion", "Choose a workout scheduled for today or earlier"}
			}
			if linked {
				return change, false, &Problem{"already_linked", "This workout already has a recording"}
			}
		}
		if linked {
			change.PreviousRecordingDay, err = q.CompletionSubjectDate(ctx, db.CompletionSubjectDateParams{
				AthleteZone: zone, ActivityID: old.ActivityID, StrongWorkoutID: old.StrongWorkoutID, ManualSessionID: old.ManualSessionID,
			})
			if err != nil {
				return change, false, err
			}
		}
	}
	if !linked && input.Status == Unknown && (old.Status == string(Skipped) || old.Status == string(CompletedAsPlanned)) {
		return change, true, q.DeleteCompletion(ctx, id)
	}

	reason, note := textValue(input.ModificationReason), textValue(input.ReasonNote)
	changed := linked || old.Status != string(input.Status) || old.MatchMethod != "user_marked" || old.ModificationReason != reason || old.ReasonNote != note
	version, inputVersion := old.Version, old.InputVersion
	if changed {
		version++
		inputVersion++
	}
	saved, err := q.SaveSelfReport(ctx, db.SaveSelfReportParams{
		SessionUid: id, Status: string(input.Status), ModificationReason: reason, ReasonNote: note,
		Version: version, InputVersion: inputVersion, UpdatedAt: pgtype.Timestamptz{Time: now, Valid: true},
	})
	if err == nil {
		change.After = &saved
	}
	return change, changed, err
}
