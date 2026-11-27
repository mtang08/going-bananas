package planning

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type Event struct {
	ID       uuid.UUID `json:"id"`
	Name     string    `json:"name"`
	Date     string    `json:"event_date"`
	Distance *int      `json:"distance_m"`
	Purpose  string    `json:"purpose"`
	GoalTime *int      `json:"goal_time_s"`
	Status   string    `json:"status"`
	Result   *int      `json:"result_s"`
	Version  int       `json:"version"`
	Rank     *int      `json:"rank"`
}
type EventOrderItem struct {
	ID      uuid.UUID `json:"id"`
	Version int       `json:"expected_version"`
}
type Problem struct {
	Status        int
	Code, Message string
}

func (p *Problem) Error() string { return p.Message }

const ranked = `WITH upcoming AS (SELECT id,row_number() over(order by rank nulls last,event_date,id) AS pos FROM events WHERE status IN ('planned','registered') AND event_date >= $1::date)`

func Events(ctx context.Context, tx pgx.Tx, today string) ([]Event, error) {
	rows, err := tx.Query(ctx, ranked+` SELECT e.id,name,event_date::text,distance_m,purpose,goal_time_s,status,result_s,version,pos FROM events e LEFT JOIN upcoming USING(id) ORDER BY event_date,e.id`, today)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowToStructByPos[Event])
}
func renumber(ctx context.Context, tx pgx.Tx, today string) (bool, error) {
	tag, err := tx.Exec(ctx, ranked+` UPDATE events e SET rank=r.pos FROM (SELECT e2.id,u.pos FROM events e2 LEFT JOIN upcoming u USING(id)) r WHERE e.id=r.id AND e.rank IS DISTINCT FROM r.pos`, today)
	return tag.RowsAffected() > 0, err
}

// SaveEvent accepts a schema-normalized document. On update, only authored
// fields are present, so an explicit null clears an optional race result.
func SaveEvent(ctx context.Context, tx pgx.Tx, today string, id *uuid.UUID, fields json.RawMessage, expected int) (Event, error) {
	var e Event
	if id != nil {
		err := tx.QueryRow(ctx, `SELECT id,name,event_date::text,distance_m,purpose,goal_time_s,status,result_s,version,rank FROM events WHERE id=$1`, id).Scan(&e.ID, &e.Name, &e.Date, &e.Distance, &e.Purpose, &e.GoalTime, &e.Status, &e.Result, &e.Version, &e.Rank)
		if errors.Is(err, pgx.ErrNoRows) {
			return e, &Problem{404, "event_not_found", "Event not found"}
		}
		if err != nil {
			return e, err
		}
		if e.Version != expected {
			return e, &Problem{409, "version_conflict", "Event changed; reload before editing"}
		}
	}
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(fields, &obj); err != nil {
		return e, err
	}
	for _, k := range []string{"name", "event_date", "purpose", "status"} {
		if string(obj[k]) == "null" {
			return e, &Problem{422, "invalid_event", "Required event fields cannot be null"}
		}
	}
	if err := json.Unmarshal(fields, &e); err != nil {
		return e, err
	}
	if id == nil {
		e.ID = uuid.New()
	}
	e.Version++
	_, err := tx.Exec(ctx, `INSERT INTO events(id,name,event_date,distance_m,purpose,goal_time_s,status,result_s,version) VALUES($1,$2,$3::date,$4,$5,$6,$7,$8,$9)
 ON CONFLICT(id) DO UPDATE SET name=excluded.name,event_date=excluded.event_date,distance_m=excluded.distance_m,purpose=excluded.purpose,goal_time_s=excluded.goal_time_s,status=excluded.status,result_s=excluded.result_s,version=excluded.version`, e.ID, e.Name, e.Date, e.Distance, e.Purpose, e.GoalTime, e.Status, e.Result, e.Version)
	if err != nil {
		return e, err
	}
	if _, err = renumber(ctx, tx, today); err != nil {
		return e, err
	}
	err = tx.QueryRow(ctx, `SELECT rank FROM events WHERE id=$1`, e.ID).Scan(&e.Rank)
	return e, err
}
func OrderEvents(ctx context.Context, tx pgx.Tx, today string, items []EventOrderItem) ([]Event, bool, error) {
	events, err := Events(ctx, tx, today)
	if err != nil {
		return nil, false, err
	}
	current := map[uuid.UUID]Event{}
	for _, e := range events {
		if e.Rank != nil {
			current[e.ID] = e
		}
	}
	stale := &Problem{409, "event_order_stale", "Events changed; reload before reordering"}
	if len(current) != len(items) {
		return nil, false, stale
	}
	ordered := make([]Event, 0, len(items))
	for _, item := range items {
		e, ok := current[item.ID]
		if !ok {
			return nil, false, stale
		}
		delete(current, item.ID)
		ordered = append(ordered, e)
	}
	changed := false
	for i, e := range ordered {
		if e.Version != items[i].Version {
			return nil, false, &Problem{409, "version_conflict", "Event changed; reload before reordering"}
		}
		rank := i + 1
		if *e.Rank != rank {
			e.Version++
		}
		e.Rank = &rank
		tag, err := tx.Exec(ctx, `UPDATE events SET rank=$2,version=$3 WHERE id=$1 AND (rank IS DISTINCT FROM $2 OR version <> $3)`, e.ID, rank, e.Version)
		if err != nil {
			return nil, false, err
		}
		changed = changed || tag.RowsAffected() > 0
		ordered[i] = e
	}
	normalized, err := renumber(ctx, tx, today)
	return ordered, changed || normalized, err
}
