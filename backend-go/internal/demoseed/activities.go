package demoseed

import (
	"context"
	"math"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

type demoLap struct {
	seconds int
	speed   *float64
	hr      int
	step    *int
}

func ptr[T any](v T) *T { return &v }
func laps(ago, timer int, speed *float64) []demoLap {
	if ago != 6 && ago != 12 && ago != 14 && ago != 18 && ago != 22 {
		return []demoLap{{timer, speed, 140, nil}}
	}
	set := []demoLap{{600, ptr(2.8), 140, ptr(0)}}
	if ago == 14 {
		set = []demoLap{{300, ptr(2.8), 140, ptr(0)}, {300, ptr(2.8), 140, ptr(0)}}
	}
	count := 4
	if ago == 12 || ago == 18 {
		count = 5
	}
	for i := range count {
		l := demoLap{300, ptr(3.6), 158, ptr(1)}
		switch ago {
		case 6:
			l.hr = 158 + 2*i
			if i == 2 {
				l.speed = ptr(3.4)
			}
		case 12:
			l.speed = ptr(3.5)
		case 18:
			l.seconds = 240
			l.speed = ptr(3.7)
			l.hr = 163
		case 22:
			l.speed = ptr(3.45)
			l.hr = 160
			if i == 3 {
				l.seconds = 250
				l.hr = 165
			}
		}
		set = append(set, l)
		if ago != 14 || i < count-1 {
			set = append(set, demoLap{120, ptr(2.5), 140, ptr(2)})
		}
	}
	return append(set, demoLap{600, ptr(2.8), 140, ptr(4)})
}
func fitRows(ctx context.Context, tx pgx.Tx, id uuid.UUID, start time.Time, ago, timer int, speed *float64) error {
	var present bool
	if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM activity_laps WHERE activity_id=$1)", id).Scan(&present); err != nil || present {
		return err
	}
	specs := laps(ago, timer, speed)
	seconds := make([]int, timer)
	hr := make([]int16, timer)
	speeds := make([]*float32, timer)
	distances := make([]*float32, timer)
	altitudes := make([]*float32, timer)
	offset := 0
	distance := 0.0
	for i, l := range specs {
		total, maxHR := 0, 0
		for sec := offset; sec < offset+l.seconds; sec++ {
			bpm := l.hr
			if len(specs) == 1 {
				drift := 3.0
				if timer >= 3600 {
					drift = 6
				}
				bpm = int(math.RoundToEven(146 - 0.3*float64(28-ago) + drift*float64(sec)/float64(timer)))
			}
			total += bpm
			maxHR = max(maxHR, bpm)
			seconds[sec] = sec
			hr[sec] = int16(bpm)
			if l.speed != nil {
				distance += *l.speed
				distances[sec] = ptr(float32(distance))
				speeds[sec] = ptr(float32(*l.speed))
			}
			if speed != nil {
				v := 50.0
				if ago == 26 {
					v += 20 * math.Sin(2*math.Pi*float64(sec)/600)
				}
				altitudes[sec] = ptr(float32(v))
			}
		}
		var length *float64
		if l.speed != nil {
			length = ptr(float64(l.seconds) * *l.speed)
		}
		trigger := "time"
		if i == len(specs)-1 {
			trigger = "session_end"
		}
		_, err := tx.Exec(ctx, `INSERT INTO activity_laps(id,activity_id,lap_index,start_at,timer_s,elapsed_s,distance_m,avg_speed_mps,avg_hr_bpm,max_hr_bpm,lap_trigger,wkt_step_index)
 VALUES(gen_random_uuid(),$1,$2,$3,$4,$4,$5,$6,$7,$8,$9,$10)`, id, i, start.Add(time.Duration(offset)*time.Second), float64(l.seconds), length, l.speed, math.RoundToEven(float64(total)/float64(l.seconds)), maxHR, trigger, l.step)
		if err != nil {
			return err
		}
		offset += l.seconds
	}
	_, err := tx.Exec(ctx, `INSERT INTO activity_streams(activity_id,t_s,hr_bpm,speed_mps,distance_m,altitude_m,cadence,timer_on,sample_count,max_gap_s,quality_flags)
 VALUES($1,$2,$3,$4,$5,$6,array_fill(NULL::real,ARRAY[$7::int]),ARRAY[ARRAY[0,$7::int]],$7,1,'{}')`, id, seconds, hr, speeds, distances, altitudes, timer)
	if err != nil || len(specs) == 1 {
		return err
	}
	count, work := 4, 300
	if ago == 12 || ago == 18 {
		count = 5
	}
	if ago == 18 {
		work = 240
	}
	_, err = tx.Exec(ctx, `INSERT INTO activity_workout_steps(id,activity_id,message_index,step_name,intensity,duration_type,duration_value,target_type,target_low,target_high,repeat_from,repeat_count) VALUES
 (gen_random_uuid(),$1,0,'Warm up','warmup','time',600,NULL,NULL,NULL,NULL,NULL),
 (gen_random_uuid(),$1,1,'Work','active','time',$2,'speed',3.4,3.8,NULL,NULL),
 (gen_random_uuid(),$1,2,'Recover','recovery','time',120,NULL,NULL,NULL,NULL,NULL),
 (gen_random_uuid(),$1,3,NULL,NULL,'repeat_until_steps_cmplt',NULL,NULL,NULL,NULL,1,$3),
 (gen_random_uuid(),$1,4,'Cool down','cooldown','time',600,NULL,NULL,NULL,NULL,NULL)`, id, work, count)
	return err
}
func seedActivities(ctx context.Context, tx pgx.Tx, root string, account uuid.UUID, today, now time.Time) error {
	times := map[int]int{2: 4800, 6: 2880, 12: 3300, 14: 2760, 18: 3000, 22: 2830}
	for _, ago := range []int{28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 2, 1} {
		timer := times[ago]
		if timer == 0 {
			timer = 1800
		}
		day := today.AddDate(0, 0, -ago)
		minute := 0
		if ago == 1 {
			minute = 30
		}
		start := time.Date(day.Year(), day.Month(), day.Day(), 7, minute, 0, 0, today.Location()).UTC()
		kind := "running"
		speed := ptr(2.8)
		if ago == 20 {
			speed = nil
			kind = "treadmill_running"
		}
		row := map[string]any{"activityId": 3000 + ago, "startTimeGMT": start.Format(time.RFC3339), "activityType": map[string]any{"typeKey": kind}, "elapsedDuration": timer, "movingDuration": timer}
		if speed != nil {
			row["distance"] = float64(timer) * *speed
		}
		id, err := replay.DemoActivity(ctx, tx, root, account, row, today.Location(), now)
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, `UPDATE activities SET timer_s=$2,end_at=$3,fit_status='decoded',workout_rpe=CASE WHEN $4 THEN 4 ELSE workout_rpe END WHERE id=$1`, id, timer, start.Add(time.Duration(timer)*time.Second), ago == 10); err != nil {
			return err
		}
		if err = fitRows(ctx, tx, id, start, ago, timer, speed); err != nil {
			return err
		}
		if ago == 10 {
			_, err = tx.Exec(ctx, `INSERT INTO session_rpe(id,activity_id,rpe,source,collected_at,collection_delay_s)
 SELECT gen_random_uuid(),id,4,'garmin_fit',end_at,0 FROM activities a WHERE id=$1 AND NOT EXISTS (SELECT FROM session_rpe WHERE activity_id=a.id AND source='garmin_fit')`, id)
			if err != nil {
				return err
			}
		}
	}
	return nil
}
