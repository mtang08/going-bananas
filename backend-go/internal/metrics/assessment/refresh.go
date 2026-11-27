package assessment

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

const metricID = "planned_actual_session"
const methodVersion = "v2"

var Config = object{"ratio_met": 0.9, "ratio_partial": 0.5, "exceeded": 1.15, "step_met": 1, "target_met": 0.75, "target_partial": 0.4,
	"continuous_run_rule": "whole_activity_dose.v1", "partial_rule": "any_not_met.v1", "moved_rule": "assessed.v1",
	"precedence": []string{"skipped", "moved", "extra", "partial", "modified", "as_planned", "unknown"}}

type Result struct {
	MetricResultID *uuid.UUID
	StatusChanged  bool
}
type subject struct {
	Input
	refs        object
	planRef     object
	association metrics.CompletionAssociation
	day, zone   string
	head        int
}

func load(ctx context.Context, tx pgx.Tx, uid uuid.UUID, now time.Time) (subject, error) {
	s := subject{refs: object{"session_uid": uid, "plan": nil, "completion_association_hash": nil, "activity": object{}, "interval_result_id": nil, "interval_dependency_hash": nil}}
	err := tx.QueryRow(ctx, `SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'),
		coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0)`).Scan(&s.zone, &s.head)
	if err != nil {
		return s, err
	}
	zone, err := time.LoadLocation(s.zone)
	if err != nil {
		return s, err
	}
	s.AsOf = now.In(zone).Format(time.DateOnly)
	var p Plan
	var planID uuid.UUID
	var version int
	var raw []byte
	var deleted bool
	err = tx.QueryRow(ctx, `SELECT id,revision,calendar_version_number,local_date::text,kind,certainty,planned_duration_s,planned_distance_m,structure,deleted
		FROM calendar_session_revisions WHERE session_uid=$1 AND calendar_version_number<=$2 ORDER BY calendar_version_number DESC,revision DESC LIMIT 1`, uid, s.head).Scan(
		&planID, &version, &p.Version, &p.LocalDate, &p.Kind, &p.Certainty, &p.Duration, &p.Distance, &raw, &deleted)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return s, err
	}
	if err == nil && !deleted {
		s.Plan = &p
		s.day = p.LocalDate
		if raw != nil {
			if err := json.Unmarshal(raw, &p.Steps); err != nil {
				return s, err
			}
		}
		value, err := metrics.JSONValue(raw)
		if err != nil {
			return s, err
		}
		hash, err := metrics.Digest(value)
		if err != nil {
			return s, err
		}
		s.refs["plan"] = object{"revision_id": planID, "revision": version, "calendar_version": p.Version, "structure_hash": hash}
		s.planRef = object{"session_uid": uid, "revision_id": planID, "calendar_version": s.head, "structure_hash": hash}
	}
	var c Completion
	a := &s.association
	a.SessionUID = uid
	err = tx.QueryRow(ctx, `SELECT status,match_method,modification_reason,reason_note,input_version,activity_id,strong_workout_id,manual_session_id
		FROM session_completions WHERE session_uid=$1`, uid).Scan(&c.Status, &a.MatchMethod, &a.ModificationReason, &a.ReasonNote, &a.InputVersion, &a.ActivityID, &a.StrongWorkoutID, &a.ManualSessionID)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return s, err
	}
	if err == nil {
		s.Completion = &c
		c.Method = a.MatchMethod
		if a.ModificationReason != nil {
			c.Reason = *a.ModificationReason
		}
		hash, err := a.Hash()
		if err != nil {
			return s, err
		}
		s.refs["completion_association_hash"] = hash
		if err := s.loadActivity(ctx, tx); err != nil {
			return s, err
		}
	}
	if s.Plan != nil {
		s.Candidates, err = candidates(ctx, tx, uid, s.day, s.zone, s.head)
		if err != nil {
			return s, err
		}
	}
	if s.day != "" {
		err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM coverage_intervals WHERE dataset='activities' AND status='complete' AND fully_enumerated
			AND start_date<=$1::text::date AND end_date>=$1::text::date)`, s.day).Scan(&s.Coverage)
		if err != nil {
			return s, err
		}
	}
	return s, nil
}

func (s *subject) loadActivity(ctx context.Context, tx pgx.Tx) error {
	a := s.association
	var day string
	switch {
	case a.ActivityID != nil:
		s.Completion.Activity = a.ActivityID.String()
		actual, refs, d, err := runActivity(ctx, tx, *a.ActivityID, s.zone, s.planRef, s.refs["completion_association_hash"])
		if err != nil {
			return err
		}
		s.Activity, s.refs["activity"], day = actual, refs, d
		var id uuid.UUID
		var hash string
		var raw []byte
		err = tx.QueryRow(ctx, `SELECT id,dependency_hash,value FROM metric_results WHERE metric_id='work_interval_execution' AND method_version='v2'
			AND is_current AND subject_key=$1`, a.ActivityID.String()).Scan(&id, &hash, &raw)
		if err == nil {
			s.refs["interval_result_id"] = id
			s.refs["interval_dependency_hash"] = hash
			s.Intervals = intervalComponents(raw)
		} else if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
	case a.StrongWorkoutID != nil:
		s.Completion.Strong = a.StrongWorkoutID.String()
		actual := Activity{Kind: "strength"}
		var source, raw uuid.UUID
		var hash, rawHash, parser *string
		var payload, state string
		ref := object{"strong_workout_id": a.StrongWorkoutID}
		err := tx.QueryRow(ctx, `SELECT w.duration_s,w.local_date::text,w.source_record_id,w.raw_object_id,w.payload_hash,w.resolution_state,s.payload_hash,s.parser_version,r.sha256
			FROM strong_workouts w LEFT JOIN source_records s ON s.id=w.source_record_id LEFT JOIN raw_objects r ON r.id=w.raw_object_id WHERE w.id=$1`, a.StrongWorkoutID).Scan(
			&actual.Timer, &day, &source, &raw, &payload, &state, &hash, &parser, &rawHash)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if err == nil && state == "resolved" {
			s.Activity = &actual
			ref["source_record_id"] = source
			ref["raw_object_id"] = raw
			ref["source_payload_hash"] = hash
			ref["source_parser_version"] = parser
			ref["raw_sha256"] = rawHash
			ref["payload_hash"] = payload
		}
		s.refs["activity"] = ref
	case a.ManualSessionID != nil:
		s.Completion.Manual = a.ManualSessionID.String()
		var actual Activity
		var version int
		var clock *string
		ref := object{"manual_session_id": a.ManualSessionID}
		err := tx.QueryRow(ctx, `SELECT kind,duration_s,date::text,version,
			CASE WHEN "time" IS NOT NULL THEN to_char("time",'HH24:MI:SS') || CASE WHEN extract(microseconds FROM "time")::int%1000000=0 THEN '' ELSE to_char("time",'.US') END END
			FROM manual_sessions WHERE id=$1`, a.ManualSessionID).Scan(&actual.Kind, &actual.Timer, &day, &version, &clock)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if err == nil {
			hash, err := metrics.Digest(object{"version": version, "date": day, "time": clock, "duration_s": actual.Timer, "kind": actual.Kind})
			if err != nil {
				return err
			}
			ref["version"] = version
			ref["source_revision"] = hash
			s.Activity = &actual
		}
		s.refs["activity"] = ref
	}
	if s.day == "" {
		s.day = day
	}
	return nil
}

func intervalComponents(b []byte) *Intervals {
	var v struct {
		Intervals
		NPlanned   *int `json:"n_planned"`
		NCompleted *int `json:"n_completed"`
		Reps       []struct {
			Valid   *float64 `json:"target_valid_s"`
			InRange *float64 `json:"target_in_range_s"`
		} `json:"reps"`
	}
	if len(b) == 0 || json.Unmarshal(b, &v) != nil {
		return nil
	}
	var valid, inRange float64
	var n, m int
	for _, rep := range v.Reps {
		if rep.Valid != nil {
			valid += *rep.Valid
			n++
		}
		if rep.InRange != nil {
			inRange += *rep.InRange
			m++
		}
	}
	if valid > 0 && n == m {
		r := inRange / valid
		v.Target = &r
	}
	if v.NPlanned != nil && *v.NPlanned > 0 && v.NCompleted != nil {
		r := float64(*v.NCompleted) / float64(*v.NPlanned)
		v.Step = &r
	}
	return &v.Intervals
}

// Refresh evaluates one session at now, using the transaction's current interval
// results. The caller owns the transaction, the global write lock, and commit.
func Refresh(ctx context.Context, tx pgx.Tx, uid uuid.UUID, now time.Time) (Result, error) {
	return refresh(ctx, tx, uid, now, true)
}

func RefreshBatch(ctx context.Context, tx pgx.Tx, uids []uuid.UUID, now time.Time) error {
	changed := false
	for _, id := range uids {
		result, err := refresh(ctx, tx, id, now, false)
		if err != nil {
			return err
		}
		changed = changed || result.StatusChanged
	}
	if changed {
		_, err := db.New(tx).BumpDataRevision(ctx)
		return err
	}
	return nil
}

// Calculate returns a planned-versus-actual result without selecting or persisting it.
func Calculate(ctx context.Context, tx pgx.Tx, uid uuid.UUID, now time.Time) (*metrics.Result, error) {
	s, err := load(ctx, tx, uid, now)
	if err != nil {
		return nil, err
	}
	if s.Plan == nil && s.Completion == nil {
		return nil, nil
	}
	r, _, err := resultFor(s, uid)
	return r, err
}
func resultFor(s subject, uid uuid.UUID) (*metrics.Result, *string, error) {
	out, err := Assess(s.Input)
	if err != nil {
		return nil, nil, err
	}
	s.refs["candidate_activity_ids"] = out.Value.CandidateIDs
	s.refs["coverage_complete"] = s.Coverage
	s.refs["as_of"] = s.AsOf
	h, err := metrics.Digest(s.refs)
	if err != nil {
		return nil, nil, err
	}
	s.refs["input_hash"] = h
	quality := ""
	if out.Quality != nil {
		quality = *out.Quality
	}
	return &metrics.Result{MetricID: metricID, MethodVersion: methodVersion, SubjectType: "session", SubjectKey: uid.String(), WindowLabel: s.day, Status: out.Status, QualityStatus: quality, Value: out.Value, ReasonCodes: out.Reasons, QualityFlags: out.Flags, SourceRefs: s.refs, Config: Config, Timezone: s.zone}, out.Derived, nil
}
func refresh(ctx context.Context, tx pgx.Tx, uid uuid.UUID, now time.Time, bump bool) (Result, error) {
	s, err := load(ctx, tx, uid, now)
	if err != nil {
		return Result{}, err
	}
	if s.Plan == nil && s.Completion == nil {
		_, err = tx.Exec(ctx, `UPDATE metric_results SET is_current=false WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current`, metricID, methodVersion, uid.String())
		return Result{}, err
	}
	row, derived, err := resultFor(s, uid)
	if err != nil {
		return Result{}, err
	}
	id, err := metrics.StoreResult(ctx, tx, *row, now)
	if err != nil {
		return Result{}, err
	}
	result := Result{MetricResultID: &id}
	if derived != nil && s.Completion != nil && s.Completion.Status != *derived {
		_, err = tx.Exec(ctx, `UPDATE session_completions SET status=$2,version=version+1,updated_at=$3 WHERE session_uid=$1`, uid, *derived, now)
		if err != nil {
			return Result{}, err
		}
		if bump {
			if _, err = db.New(tx).BumpDataRevision(ctx); err != nil {
				return Result{}, err
			}
		}
		result.StatusChanged = true
	}
	return result, nil
}
