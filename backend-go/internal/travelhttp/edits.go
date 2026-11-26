package travelhttp

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func (h Handler) createTrip(w http.ResponseWriter, r *http.Request) { h.edit(w, r, "createTrip") }
func (h Handler) patchTrip(w http.ResponseWriter, r *http.Request)  { h.edit(w, r, "patchTrip") }
func (h Handler) patchEvent(w http.ResponseWriter, r *http.Request) { h.edit(w, r, "patchEvent") }

func (h Handler) edit(w http.ResponseWriter, r *http.Request, operation string) {
	req, fields := readEdit(r.Body, operation)
	var id uuid.UUID
	if operation != "createTrip" && (len(fields) != 1 || fields[0].Message != "JSON decode error") {
		key := "trip_id"
		if operation == "patchEvent" {
			key = "event_id"
		}
		var msg string
		id, msg = editUUID(r.PathValue(key))
		if msg != "" {
			fields = append([]Field{{"path." + key, msg}}, fields...)
		}
	}
	if len(fields) > 0 {
		invalid(w, r, fields)
		return
	}
	ctx := r.Context()
	var data any
	var revision int32
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		home, err := athleteHome(ctx, tx)
		if err != nil {
			return err
		}
		data, err = h.applyEdit(ctx, tx, home, operation, id, req)
		if err != nil {
			return err
		}
		revision, err = q.BumpDataRevision(ctx)
		return err
	})
	if err != nil {
		switch {
		case errors.Is(err, travel.ErrTripNotFound):
			fail(w, r, 404, "trip_not_found", "Trip not found")
		case errors.Is(err, travel.ErrEventNotFound):
			fail(w, r, 404, "event_not_found", "Calendar event not found")
		case errors.Is(err, travel.ErrTripConflict):
			fail(w, r, 409, "version_conflict", "Trip changed; reload before editing")
		case errors.Is(err, travel.ErrEventConflict):
			fail(w, r, 409, "version_conflict", "Calendar event changed; reload before editing")
		case errors.Is(err, travel.ErrInvalidTrip):
			fail(w, r, 422, "invalid_trip", "Trip dates or availability are invalid")
		default:
			writeError(w, r, err)
		}
		return
	}
	status := http.StatusOK
	if operation == "createTrip" {
		status = http.StatusCreated
	}
	h.respond(w, r, status, data, revision)
}

func (h Handler) applyEdit(ctx context.Context, tx pgx.Tx, home *time.Location, operation string, id uuid.UUID, req editRequest) (any, error) {
	if operation == "patchEvent" {
		counts, err := travel.PatchEventCategory(ctx, tx, id, req.trip.ExpectedVersion, req.category, home)
		if err != nil {
			return nil, err
		}
		event, err := eventByID(ctx, tx, id, home)
		if err != nil {
			return nil, err
		}
		return struct {
			Event EventView         `json:"event"`
			Trips travel.TripCounts `json:"trips"`
		}{event, counts}, nil
	}
	var err error
	if operation == "createTrip" {
		id, err = travel.CreateManualTrip(ctx, tx, req.trip, h.now())
	} else {
		err = travel.PatchTrip(ctx, tx, id, req.trip, h.now())
	}
	if err != nil {
		return nil, err
	}
	return tripByID(ctx, tx, id, home)
}
