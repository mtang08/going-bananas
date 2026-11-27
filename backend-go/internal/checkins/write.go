package checkins

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

func lock(ctx context.Context, tx pgx.Tx) error {
	if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
		return err
	}
	var rev int
	return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1 FOR UPDATE").Scan(&rev)
}

func fromView(v View) (Input, error) {
	t, err := time.Parse(time.RFC3339Nano, v.ObservedAt)
	return normalized(Input{v.IdempotencyKey, v.Kind, t, v.Fatigue, v.Illness, v.GaitChange, v.PainReported, v.ContextTags, v.ActivityID, v.PromptID, v.Note, v.Symptoms}), err
}

func normalized(in Input) Input {
	in.ObservedAt = in.ObservedAt.UTC().Truncate(time.Microsecond)
	if in.ContextTags == nil {
		in.ContextTags = []string{}
	}
	in.Symptoms = slices.Clone(in.Symptoms)
	if in.Symptoms == nil {
		in.Symptoms = []Symptom{}
	}
	for i := range in.Symptoms {
		in.Symptoms[i].ID = nil
	}
	return in
}

func validatePain(in Input) error {
	if in.PainReported != nil && !*in.PainReported && len(in.Symptoms) > 0 {
		return problem("invalid_checkin", "No pain cannot be combined with symptom reports", 422)
	}
	return nil
}

func addSymptoms(ctx context.Context, tx pgx.Tx, id uuid.UUID, reports []Symptom) error {
	if len(reports) >= 65535 {
		return problem("invalid_checkin", "Too many symptom reports", 422)
	}
	for i, s := range reports {
		if _, err := tx.Exec(ctx, `INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing) VALUES($1,$2,$3,$4,$5,$6)`,
			symptomID(id, i+1), id, s.Site, s.Side, s.Severity, s.Timing); err != nil {
			return err
		}
	}
	return nil
}

func answer(ctx context.Context, tx pgx.Tx, prompt *uuid.UUID) error {
	if prompt == nil {
		return nil
	}
	_, err := tx.Exec(ctx, "UPDATE prompts SET status='answered' WHERE id=$1 AND status<>'answered'", prompt)
	return err
}

func Create(ctx context.Context, tx pgx.Tx, in Input, now time.Time) (View, bool, error) {
	if err := lock(ctx, tx); err != nil {
		return View{}, false, err
	}
	in = normalized(in)
	current, err := scanView(tx.QueryRow(ctx, viewSelect+" WHERE c.idempotency_key=$1", in.IdempotencyKey))
	if err == nil {
		var original View
		err = tx.QueryRow(ctx, "SELECT payload FROM checkin_v2_revisions WHERE checkin_id=$1 ORDER BY version LIMIT 1", current.ID).Scan(&original)
		if errors.Is(err, pgx.ErrNoRows) {
			original = current
		} else if err != nil {
			return View{}, false, err
		}
		prior, err := fromView(original)
		if err != nil {
			return View{}, false, err
		}
		if !reflect.DeepEqual(prior, in) {
			return View{}, false, problem("idempotency_conflict", "Check-in key was used for a different body", 409)
		}
		return original, false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return View{}, false, err
	}
	if err := validatePain(in); err != nil {
		return View{}, false, err
	}
	if err := related(ctx, tx, in, nil, now); err != nil {
		return View{}, false, err
	}
	id := uuid.New()
	_, err = tx.Exec(ctx, `INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,fatigue,illness,gait_change,pain_reported,context_tags,activity_id,prompt_id,note)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`, id, in.IdempotencyKey, in.Kind, in.ObservedAt, in.Fatigue, in.Illness, in.GaitChange, in.PainReported, in.ContextTags, in.ActivityID, in.PromptID, in.Note)
	if err != nil {
		return View{}, false, err
	}
	if err := addSymptoms(ctx, tx, id, in.Symptoms); err != nil {
		return View{}, false, err
	}
	if err := answer(ctx, tx, in.PromptID); err != nil {
		return View{}, false, err
	}
	v, err := get(ctx, tx, id)
	return v, true, err
}

func patch(ctx context.Context, tx pgx.Tx, id uuid.UUID, expected int, changes map[string]json.RawMessage, now time.Time) (View, View, error) {
	if err := lock(ctx, tx); err != nil {
		return View{}, View{}, err
	}
	prior, err := get(ctx, tx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return View{}, View{}, problem("checkin_not_found", "Check-in not found", 404)
	}
	if err != nil {
		return View{}, View{}, err
	}
	if strings.HasPrefix(prior.IdempotencyKey, FirstStepsKey) {
		return View{}, View{}, problem("immutable_morning_checkin", "The submitted morning observation is read-only", 409)
	}
	if expected != prior.Version {
		return View{}, View{}, problem("version_conflict", "Check-in changed; reload before editing", 409)
	}
	in, err := fromView(prior)
	if err != nil {
		return View{}, View{}, err
	}
	for _, key := range []string{"observed_at", "kind", "context_tags", "symptoms"} {
		if v, ok := changes[key]; ok && strings.TrimSpace(string(v)) == "null" {
			return View{}, View{}, problem("invalid_checkin", "Required check-in fields cannot be null", 422)
		}
	}
	raw, err := json.Marshal(changes)
	if err != nil {
		return View{}, View{}, err
	}
	if err := json.Unmarshal(raw, &in); err != nil {
		return View{}, View{}, err
	}
	in = normalized(in)
	if err := validatePain(in); err != nil {
		return View{}, View{}, err
	}
	if err := related(ctx, tx, in, &prior, now); err != nil {
		return View{}, View{}, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO checkin_v2_revisions(id,checkin_id,version,payload) VALUES(gen_random_uuid(),$1,$2,$3::jsonb)`, id, prior.Version, prior); err != nil {
		return View{}, View{}, err
	}
	_, err = tx.Exec(ctx, `UPDATE checkins_v2 SET kind=$2,observed_at=$3,fatigue=$4,illness=$5,gait_change=$6,pain_reported=$7,
		context_tags=$8,activity_id=$9,prompt_id=$10,note=$11,version=version+1 WHERE id=$1`, id, in.Kind, in.ObservedAt, in.Fatigue, in.Illness, in.GaitChange, in.PainReported, in.ContextTags, in.ActivityID, in.PromptID, in.Note)
	if err != nil {
		return View{}, View{}, err
	}
	if _, ok := changes["symptoms"]; ok {
		if _, err := tx.Exec(ctx, "DELETE FROM symptom_reports WHERE checkin_id=$1", id); err != nil {
			return View{}, View{}, err
		}
		if err := addSymptoms(ctx, tx, id, in.Symptoms); err != nil {
			return View{}, View{}, err
		}
	}
	if err := answer(ctx, tx, in.PromptID); err != nil {
		return View{}, View{}, err
	}
	v, err := get(ctx, tx, id)
	return v, prior, err
}
