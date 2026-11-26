package travel

import (
	"context"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

type TripCounts struct {
	changed bool
	Created int `json:"created"`
	Updated int `json:"updated"`
	Flagged int `json:"flagged"`
	Deleted int `json:"deleted"`
}

type storedTrip struct {
	id, status, start, reason string
	edited, empty, claimed    bool
}

func detectedOwners(ctx context.Context, tx pgx.Tx) (map[string]*storedTrip, map[string]*storedTrip, error) {
	rows, err := tx.Query(ctx, `SELECT id::text,status,to_char(start_date,'YYYY-MM-DD'),coalesce(review_reason,''),edited,detected='{}'::jsonb FROM trips WHERE source='detected' ORDER BY id FOR UPDATE`)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	trips := make(map[string]*storedTrip)
	for rows.Next() {
		t := new(storedTrip)
		if err := rows.Scan(&t.id, &t.status, &t.start, &t.reason, &t.edited, &t.empty); err != nil {
			return nil, nil, err
		}
		trips[t.id] = t
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	links, err := tx.Query(ctx, `SELECT l.gcal_event_id::text,l.trip_id::text FROM trip_legs l JOIN trips t ON t.id=l.trip_id WHERE t.source='detected'`)
	if err != nil {
		return nil, nil, err
	}
	defer links.Close()
	owners := make(map[string]*storedTrip)
	for links.Next() {
		var id, trip string
		if err := links.Scan(&id, &trip); err != nil {
			return nil, nil, err
		}
		owners[id] = trips[trip]
	}
	return trips, owners, links.Err()
}

func preferredOwner(legs []flightLeg, owners map[string]*storedTrip) *storedTrip {
	var best *storedTrip
	for _, l := range legs {
		t := owners[l.id]
		if t == nil {
			for _, alias := range l.aliases {
				if t = owners[alias]; t != nil {
					break
				}
			}
		}
		if t == nil || t.claimed && t.status != "dismissed" {
			continue
		}
		if best == nil || (t.status == "dismissed" && best.status != "dismissed") {
			best = t
			continue
		}
		if (t.status == "dismissed") != (best.status == "dismissed") {
			continue
		}
		if t.start < best.start || t.start == best.start && t.id < best.id {
			best = t
		}
	}
	return best
}

type legLink struct{ ID, Hash string }

func linksFor(legs []flightLeg) []legLink {
	links := make([]legLink, len(legs))
	for i, l := range legs {
		links[i] = legLink{l.id, l.hash}
	}
	return links
}

func putLegs(ctx context.Context, tx pgx.Tx, tripID string, links []legLink, appendOnly bool) error {
	ids := make([]string, len(links))
	hashes := make([]string, len(links))
	for i, l := range links {
		ids[i], hashes[i] = l.ID, l.Hash
	}
	_, err := tx.Exec(ctx, `DELETE FROM trip_legs WHERE gcal_event_id=ANY($1::text[]::uuid[]) OR (NOT $2::bool AND trip_id=$3::uuid)`, ids, appendOnly, tripID)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO trip_legs(id,trip_id,gcal_event_id,leg_hash,seq)
		SELECT gen_random_uuid(),$1::uuid,id::uuid,hash,COALESCE((SELECT max(seq)+1 FROM trip_legs WHERE trip_id=$1::uuid),0)+ord-1
		FROM unnest($2::text[],$3::text[]) WITH ORDINALITY AS l(id,hash,ord)`, tripID, ids, hashes)
	return err
}

func mergeCandidate(ctx context.Context, tx pgx.Tx, t *storedTrip, c tripCandidate, counts *TripCounts) error {
	rows, err := tx.Query(ctx, `SELECT gcal_event_id::text,leg_hash FROM trip_legs WHERE trip_id=$1::uuid ORDER BY seq`, t.id)
	if err != nil {
		return err
	}
	current, err := pgx.CollectRows(rows, pgx.RowToStructByPos[legLink])
	if err != nil {
		return err
	}
	wanted := linksFor(c.legs)
	if t.status == "dismissed" {
		have := make(map[string]bool, len(current))
		for _, l := range current {
			have[l.ID] = true
		}
		newLinks := slices.DeleteFunc(wanted, func(l legLink) bool { return have[l.ID] })
		if len(newLinks) == 0 {
			return nil
		}
		counts.changed = true
		return putLegs(ctx, tx, t.id, newLinks, true)
	}
	if slices.Equal(current, wanted) {
		var same bool
		if err := tx.QueryRow(ctx, `SELECT detected=$2::jsonb FROM trips WHERE id=$1::uuid`, t.id, c.detectedTrip).Scan(&same); err != nil {
			return err
		}
		if same {
			return nil
		}
	}
	if err := putLegs(ctx, tx, t.id, wanted, false); err != nil {
		return err
	}
	if t.status == "pending" && !t.edited {
		_, err = tx.Exec(ctx, `UPDATE trips SET detected=$2::jsonb,start_date=$3::text::date,end_date=$4::text::date,
			destination_label=$5,destination_tz=$6,confidence=$7,version=version+1 WHERE id=$1::uuid`,
			t.id, c.detectedTrip, c.Start, c.End, c.Label, c.Zone, c.Confidence)
		counts.Updated++
	} else {
		_, err = tx.Exec(ctx, `UPDATE trips SET detected=$2::jsonb,status='needs_review',review_reason='source_changed',version=version+1 WHERE id=$1::uuid`, t.id, c.detectedTrip)
		counts.Flagged++
	}
	return err
}

func unmatchedTrip(ctx context.Context, tx pgx.Tx, t *storedTrip, counts *TripCounts) error {
	if t.status == "dismissed" || t.reason == "source_removed" || t.status == "confirmed" && t.empty {
		return nil
	}
	if t.status == "pending" && !t.edited {
		_, err := tx.Exec(ctx, `DELETE FROM trips WHERE id=$1::uuid`, t.id)
		counts.Deleted++
		return err
	}
	_, err := tx.Exec(ctx, `UPDATE trips SET detected='{}'::jsonb,status='needs_review',review_reason='source_removed',version=version+1 WHERE id=$1::uuid`, t.id)
	counts.Flagged++
	return err
}

func reconcileTrips(ctx context.Context, tx pgx.Tx, home *time.Location) (TripCounts, error) {
	var counts TripCounts
	legs, err := flightLegs(ctx, tx, home)
	if err != nil {
		return TripCounts{}, err
	}
	trips, owners, err := detectedOwners(ctx, tx)
	if err != nil {
		return TripCounts{}, err
	}
	for _, c := range detectTrips(legs, home) {
		if t := preferredOwner(c.legs, owners); t != nil {
			t.claimed = true
			if err := mergeCandidate(ctx, tx, t, c, &counts); err != nil {
				return TripCounts{}, err
			}
			continue
		}
		var id string
		err := tx.QueryRow(ctx, `INSERT INTO trips(id,status,source,detected,start_date,end_date,destination_label,destination_tz,confidence)
			VALUES(gen_random_uuid(),'pending','detected',$1::jsonb,$2::text::date,$3::text::date,$4,$5,$6) RETURNING id::text`,
			c.detectedTrip, c.Start, c.End, c.Label, c.Zone, c.Confidence).Scan(&id)
		if err != nil {
			return TripCounts{}, err
		}
		if err := putLegs(ctx, tx, id, linksFor(c.legs), false); err != nil {
			return TripCounts{}, err
		}
		counts.Created++
	}
	for _, t := range trips {
		if !t.claimed {
			if err := unmatchedTrip(ctx, tx, t, &counts); err != nil {
				return TripCounts{}, err
			}
		}
	}
	counts.changed = counts.changed || counts.Created+counts.Updated+counts.Flagged+counts.Deleted > 0
	return counts, nil
}
