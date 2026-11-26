package calendar

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type AssessCompletion func(context.Context, pgx.Tx, uuid.UUID) error

type RecordingLink struct {
	ExpectedVersion                              int
	ActivityID, StrongWorkoutID, ManualSessionID *uuid.UUID
	ModificationReason, ReasonNote               *string
}

func nullableID(v *uuid.UUID) pgtype.UUID {
	if v == nil {
		return pgtype.UUID{}
	}
	return pgtype.UUID{Bytes: *v, Valid: true}
}

// SaveRecordingLink accepts a pool for a standalone transaction or a transaction
// for a savepoint. Assessment and refresh share the command's transaction.
func SaveRecordingLink(ctx context.Context, conn TransactionStarter, uid uuid.UUID, link RecordingLink, now time.Time, assess AssessCompletion, refresh RefreshCompletion) (CompletionChange, error) {
	if assess == nil {
		return CompletionChange{}, errors.New("completion assessor is required")
	}
	return writeCompletion(ctx, conn, refresh, func(tx pgx.Tx, q *db.Queries, head int32) (CompletionChange, bool, error) {
		return link.apply(ctx, tx, q, uid, head, now, assess)
	})
}

func (link RecordingLink) apply(ctx context.Context, tx pgx.Tx, q *db.Queries, uid uuid.UUID, head int32, now time.Time, assess AssessCompletion) (CompletionChange, bool, error) {
	c := CompletionChange{SessionUID: uid}
	count := 0
	for _, v := range []*uuid.UUID{link.ActivityID, link.StrongWorkoutID, link.ManualSessionID} {
		if v != nil {
			count++
		}
	}
	if count != 1 {
		return c, false, &Problem{"invalid_completion", "Choose exactly one recording"}
	}
	if err := validateReason(link.ModificationReason); err != nil {
		return c, false, err
	}
	id := nullableID(&uid)
	old, err := q.CompletionForSession(ctx, id)
	if err == nil {
		c.Before = &old
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return c, false, err
	}
	if int(old.Version) != link.ExpectedVersion {
		return c, false, &Problem{"version_conflict", "Completion changed; reload before editing"}
	}
	zone, err := q.CalendarTimezone(ctx)
	if err != nil {
		return c, false, err
	}
	args := db.CompletionSubjectDateParams{
		AthleteZone:     zone,
		ActivityID:      nullableID(link.ActivityID),
		StrongWorkoutID: nullableID(link.StrongWorkoutID),
		ManualSessionID: nullableID(link.ManualSessionID),
	}
	c.RecordingDay, err = q.CompletionSubjectDate(ctx, args)
	if errors.Is(err, pgx.ErrNoRows) {
		return c, false, &Problem{"completion_subject_not_found", "Completion subject not found"}
	}
	if err != nil {
		return c, false, err
	}
	if hasRecording(c.Before) {
		c.PreviousRecordingDay, err = q.CompletionSubjectDate(ctx, db.CompletionSubjectDateParams{
			AthleteZone:     zone,
			ActivityID:      old.ActivityID,
			StrongWorkoutID: old.StrongWorkoutID,
			ManualSessionID: old.ManualSessionID,
		})
		if err != nil {
			return c, false, err
		}
	}
	c.Displaced, err = displace(ctx, q, db.RecordingHolderParams{
		SessionUid:      id,
		ActivityID:      args.ActivityID,
		StrongWorkoutID: args.StrongWorkoutID,
		ManualSessionID: args.ManualSessionID,
	}, head, c.RecordingDay, now)
	if err != nil {
		return c, false, err
	}
	plan, err := q.CompletionPlanAtHead(ctx, db.CompletionPlanAtHeadParams{
		SessionUid:            id,
		CalendarVersionNumber: head,
	})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return c, false, err
	}
	c.PlanDay = plan.LocalDate
	moved := c.PlanDay.Valid && !c.PlanDay.Time.Equal(c.RecordingDay.Time)
	method, status := "explicit", "unknown"
	if moved {
		method, status = "confirmed_move", "moved"
	}
	note, reason := textValue(link.ReasonNote), textValue(link.ModificationReason)
	changed := old.ActivityID != args.ActivityID || old.StrongWorkoutID != args.StrongWorkoutID || old.ManualSessionID != args.ManualSessionID || old.MatchMethod != method || old.ReasonNote != note || old.ModificationReason != reason
	version, inputVersion := old.Version, old.InputVersion
	if changed {
		version++
		inputVersion++
	} else {
		status = old.Status
	}
	_, err = q.SaveCompletion(ctx, db.SaveCompletionParams{SessionUid: id, ActivityID: args.ActivityID, StrongWorkoutID: args.StrongWorkoutID, ManualSessionID: args.ManualSessionID, MatchMethod: method, Status: status, Version: version, InputVersion: inputVersion, ReasonNote: note, ModificationReason: reason, UpdatedAt: pgtype.Timestamptz{Time: now, Valid: true}})
	if err != nil {
		return c, false, err
	}
	if err = assess(ctx, tx, uid); err != nil {
		return c, false, err
	}
	if moved {
		if err = q.RestoreMovedStatus(ctx, id); err != nil {
			return c, false, err
		}
	}
	saved, err := q.CompletionForSession(ctx, id)
	c.After = &saved
	return c, changed || c.Displaced != nil, err
}

func displace(ctx context.Context, q *db.Queries, args db.RecordingHolderParams, head int32, day pgtype.Date, now time.Time) (*CompletionChange, error) {
	old, err := q.RecordingHolder(ctx, args)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	conflict := &Problem{"subject_already_linked", "Subject already linked"}
	switch old.MatchMethod {
	case "explicit", "confirmed_move", "user_marked":
		return nil, conflict
	}
	change := &CompletionChange{SessionUID: uuid.UUID(old.SessionUid.Bytes), Before: &old, PreviousRecordingDay: day}
	plan, err := q.CompletionPlanAtHead(ctx, db.CompletionPlanAtHeadParams{
		SessionUid:            old.SessionUid,
		CalendarVersionNumber: head,
	})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, err
	}
	change.PlanDay = plan.LocalDate
	if old.Status == "extra" {
		return change, q.DeleteCompletion(ctx, old.SessionUid)
	}
	if old.MatchMethod != "auto_same_day" {
		return nil, conflict
	}
	after, err := q.SaveCompletion(ctx, db.SaveCompletionParams{SessionUid: old.SessionUid, Status: "unknown", MatchMethod: "none", ModificationReason: old.ModificationReason, ReasonNote: old.ReasonNote, Version: old.Version + 1, InputVersion: old.InputVersion + 1, UpdatedAt: pgtype.Timestamptz{Time: now, Valid: true}})
	change.After = &after
	return change, err
}
