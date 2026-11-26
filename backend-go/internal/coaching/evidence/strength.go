package evidence

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5"
)

// The proposal horizon includes as_of and day 42. Matching slots requires
// the entire containing weeks, including strength sessions before as_of.
const horizonDays = 42

func monday(day time.Time) time.Time {
	return day.AddDate(0, 0, -((int(day.Weekday()) + 6) % 7))
}

func weekdays(value any) map[int]bool {
	list, _ := value.([]any)
	if len(list) != 2 {
		return nil
	}
	days := map[int]bool{}
	for _, item := range list {
		var weekday int
		switch n := item.(type) {
		case json.Number:
			i, err := n.Int64()
			if err != nil {
				continue
			}
			weekday = int(i)
		case int32:
			weekday = int(n)
		case int64:
			weekday = int(n)
		default:
			continue
		}
		days[weekday] = true
	}
	return days
}

func strengthSchedule(ctx context.Context, tx pgx.Tx, asOf time.Time, profile row) ([]row, error) {
	schedule := []row{}
	if profile["strength_days_confirmed"] != true {
		return schedule, nil
	}
	weekA := weekdays(profile["scheduled_strength_days"])
	var weekB map[int]bool
	var anchor time.Time
	if profile["strength_schedule_mode"] == "alternating" {
		raw, _ := profile["strength_week_a_start"].(string)
		var err error
		anchor, err = time.Parse(time.DateOnly, raw)
		if err != nil || anchor.Weekday() != time.Monday {
			return schedule, nil
		}
		weekA = weekdays(profile["strength_week_a_days"])
		weekB = weekdays(profile["strength_week_b_days"])
		if weekB == nil {
			return schedule, nil
		}
	}
	if weekA == nil {
		return schedule, nil
	}
	slots, err := readRows(ctx, tx, `select id,label from strength_routine_slots
		where version=(select max(version) from strength_routine_slots) and active order by label collate "C", id`)
	if err != nil {
		return nil, err
	}
	last := monday(asOf.AddDate(0, 0, horizonDays)).AddDate(0, 0, 6)
	effective, _ := profile["effective_day"].(string)
	for week := monday(asOf); !week.After(last); week = week.AddDate(0, 0, 7) {
		days := weekA
		if weekB != nil && ((week.Unix()-anchor.Unix())/(7*24*3600))%2 != 0 {
			days = weekB
		}
		pos := 0
		for wd := 0; wd < 7; wd++ {
			date := week.AddDate(0, 0, wd).Format(time.DateOnly)
			if !days[wd] || date < effective {
				continue
			}
			item := row{"local_date": date, "intent": "Strength"}
			if len(slots) > 0 {
				slot := slots[pos%len(slots)]
				item["intent"], item["strength_slot_id"] = slot["label"], slot["id"]
			}
			schedule = append(schedule, item)
			pos++
		}
	}
	return schedule, nil
}

// A later non-deleted revision retires a prior exception, including undo. A
// reinstatement on a different day counts only for a unique scheduled weekly slot.
func acceptedOmissions(ctx context.Context, tx pgx.Tx, asOf time.Time, schedule []row) ([]row, error) {
	encoded, err := json.Marshal(schedule)
	if err != nil {
		return nil, err
	}
	return readRows(ctx, tx, `
	with flagged as (
		select p.id,p.decided_at,p.base_calendar_version,c.op,c.reason,coalesce(nullif(nullif(c.before,'null'::jsonb),'{}'::jsonb),c.after) as lift
		from coach_proposal_changes c join coach_proposals p on p.id=c.proposal_id
		where c.decision='accepted' and p.status in ('accepted','partially_accepted')
		and coalesce(c.before->>'local_date',c.after->>'local_date') between $1 and $2
		and p.payload->'changes' @> jsonb_build_array(jsonb_build_object('change_id',c.change_id,'material_flags',jsonb_build_array('strength_omission'::text)))
	), expected as (
		select (entry->>'local_date')::date as day,entry->>'strength_slot_id' as slot
		from jsonb_array_elements($3::jsonb) entry
	), applicable as (
		select f.*, (lift->>'local_date')::date as day, lift->>'strength_slot_id' as slot
		from flagged f where op <> 'add' or exists (
			select from expected e where e.day=(lift->>'local_date')::date
			and (coalesce(lift->>'strength_slot_id','')='' or e.slot=lift->>'strength_slot_id')
		)
	), retained as (
		select f.* from applicable f where not exists (
			select from calendar_session_revisions r where r.kind='strength' and not r.deleted
			and r.calendar_version_number > f.base_calendar_version and (
				r.local_date=f.day or (r.strength_slot_id::text=f.slot
				and date_trunc('week',r.local_date::timestamp)=date_trunc('week',f.day::timestamp)
				and 1=(select count(*) from expected e where e.slot=f.slot and
					date_trunc('week',e.day::timestamp)=date_trunc('week',f.day::timestamp)))
			)
		)
	)
	select distinct on (day) lift->>'local_date' as local_date,lift->>'intent' as intent,reason,slot as strength_slot_id
	from retained order by day,decided_at desc nulls first,id desc
	`, asOf.Format(time.DateOnly), asOf.AddDate(0, 0, horizonDays).Format(time.DateOnly), encoded)
}
