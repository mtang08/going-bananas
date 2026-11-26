package checkins

import (
	"context"
	"encoding/json"
	"errors"
	"maps"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type Detection = map[string]any

type Store struct {
	Pool    *pgxpool.Pool
	Now     func() time.Time
	Refresh func(context.Context, pgx.Tx, []string) error
	Detect  func(context.Context, pgx.Tx, time.Time) (Detection, error)
}

func (s Store) now() time.Time {
	if s.Now != nil {
		return s.Now().UTC()
	}
	return time.Now().UTC()
}

func scopes(zone *time.Location, views ...View) ([]string, error) {
	set := map[string]bool{}
	for _, v := range views {
		t, err := time.Parse(time.RFC3339Nano, v.ObservedAt)
		if err != nil {
			return nil, err
		}
		date := t.In(zone)
		set["checkin:"+v.ID.String()] = true
		set["recovery_dates:"+date.Format(time.DateOnly)] = true
		for i := 0; i < 3; i++ {
			set["date:"+date.AddDate(0, 0, -i).Format(time.DateOnly)] = true
		}
		if v.ActivityID != nil {
			set["activity:"+v.ActivityID.String()] = true
		}
	}
	return slices.Sorted(maps.Keys(set)), nil
}

func (s Store) refresh(ctx context.Context, tx pgx.Tx, views ...View) error {
	if s.Refresh == nil {
		return errors.New("check-in refresh is unavailable")
	}
	q := db.New(tx)
	zone, err := q.CalendarTimezone(ctx)
	if err != nil {
		return err
	}
	if zone == "" {
		zone = "America/New_York"
	}
	loc, err := time.LoadLocation(zone)
	if err != nil {
		return err
	}
	affected, err := scopes(loc, views...)
	if err != nil {
		return err
	}
	if _, err := q.BumpDataRevision(ctx); err != nil {
		return err
	}
	return s.Refresh(ctx, tx, affected)
}

func (s Store) detect(ctx context.Context, tx pgx.Tx) (Detection, error) {
	if s.Detect == nil {
		return nil, errors.New("check-in detector is unavailable")
	}
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return nil, err
	}
	return s.Detect(ctx, tx, s.now())
}
func revision(ctx context.Context, tx pgx.Tx) (int32, error) {
	var rev int32
	err := tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&rev)
	return rev, err
}
func (s Store) Phone(ctx context.Context, in Input) (int32, error) {
	var rev int32
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		v, created, err := Create(ctx, tx, in, s.now())
		if err != nil {
			return err
		}
		if created {
			if _, err := s.detect(ctx, tx); err != nil {
				return err
			}
			if err := s.refresh(ctx, tx, v); err != nil {
				return err
			}
		}
		rev, err = revision(ctx, tx)
		return err
	})
	return rev, err
}

func (s Store) afterDesktop(ctx context.Context) (Detection, int32, error) {
	var result Detection
	var rev int32
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		result, err = s.detect(ctx, tx)
		if err != nil {
			return err
		}
		rev, err = revision(ctx, tx)
		return err
	})
	return result, rev, err
}
func (s Store) Create(ctx context.Context, in Input) (View, bool, Detection, int32, error) {
	var v View
	var created bool
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		v, created, err = Create(ctx, tx, in, s.now())
		if err != nil || !created {
			return err
		}
		return s.refresh(ctx, tx, v)
	})
	if err != nil {
		return View{}, false, nil, 0, err
	}
	result, rev, err := s.afterDesktop(ctx)
	return v, created, result, rev, err
}

func (s Store) Patch(ctx context.Context, id uuid.UUID, expected int, changes map[string]json.RawMessage) (View, Detection, int32, error) {
	var v View
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		var prior View
		v, prior, err = patch(ctx, tx, id, expected, changes, s.now())
		if err != nil {
			return err
		}
		return s.refresh(ctx, tx, prior, v)
	})
	if err != nil {
		return View{}, nil, 0, err
	}
	result, rev, err := s.afterDesktop(ctx)
	return v, result, rev, err
}

func (s Store) List(ctx context.Context, start, end *time.Time) ([]View, int32, error) {
	var items []View
	var rev int32
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		var err error
		items, err = List(ctx, tx, start, end)
		if err != nil {
			return err
		}
		rev, err = revision(ctx, tx)
		return err
	})
	return items, rev, err
}
