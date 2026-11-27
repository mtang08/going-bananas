// Package snapshots builds and persists bounded coaching packets.
package snapshots

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/evidence"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklydigest"
)

// ErrKnowledgeUnavailable identifies failure to verify the KB required by a snapshot.
var ErrKnowledgeUnavailable = errors.New("verified research unavailable")

type Preparation func(context.Context, pgx.Tx, string, string, time.Time) error

// BuildWithPreparation executes preparation and persistence under the same lock
// and savepoint. A failed build leaves no preparation or snapshot effects.
func BuildWithPreparation(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time, kbRoot string, prepare Preparation) (map[string]any, error) {
	if prepare == nil {
		return nil, errors.New("snapshot requires metric and exception preparation")
	}
	if _, err := time.Parse(time.DateOnly, asOf); err != nil {
		return nil, err
	}
	if !Supported(operation) {
		return nil, errors.New("unsupported operation")
	}
	var packet map[string]any
	err := pgx.BeginFunc(ctx, tx, func(nested pgx.Tx) error {
		if err := db.New(nested).LockGlobalWriter(ctx); err != nil {
			return err
		}
		if _, err := nested.Exec(ctx, "SELECT id FROM app_state WHERE id=1 FOR UPDATE"); err != nil {
			return err
		}
		if err := prepare(ctx, nested, operation, asOf, now); err != nil {
			return err
		}
		var err error
		packet, err = buildPacket(ctx, nested, operation, asOf, now, kbRoot)
		return err
	})
	if err != nil {
		return nil, err
	}
	return packet, nil
}

func Supported(op string) bool {
	switch op {
	case daily, rolling, quality, blockReview, calibrate, race, exception, postEvent:
		return true
	}
	return false
}

func buildPacket(ctx context.Context, tx pgx.Tx, operation, asOf string, now time.Time, kbRoot string) (map[string]any, error) {
	var decisions evidence.Inputs
	deps := snapshotreads.InputReaders{Week: weeklydigest.LoadWeek, Strength: func(ctx context.Context, tx pgx.Tx, op, asOf string, now time.Time) (snapshotreads.StrengthInputs, error) {
		var err error
		decisions, err = evidence.CollectInputs(ctx, tx, op, asOf, now)
		if err != nil {
			return snapshotreads.StrengthInputs{}, err
		}
		omissions := []map[string]any{}
		if raw, ok := decisions.Sources["accepted_strength_omissions"]; ok {
			omissions, ok = raw.([]map[string]any)
			if !ok {
				return snapshotreads.StrengthInputs{}, errors.New("invalid accepted strength omissions")
			}
		}
		return snapshotreads.StrengthInputs{Confirmed: decisions.ConfirmedStrengthSessions, Omissions: omissions}, nil
	}}
	in, err := snapshotreads.LoadInputs(ctx, tx, operation, asOf, now, deps)
	if err != nil {
		return nil, err
	}
	recipes, topics, err := selectRoute(in, operation)
	if err != nil {
		return nil, err
	}
	route, err := coaching.LoadRoute(kbRoot, operation, recipes, topics)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrKnowledgeUnavailable, err)
	}
	_, fingerprint, err := coaching.Fingerprint(decisions.Sources, route.Knowledge)
	if err != nil {
		return nil, err
	}
	payload, err := BuildPayload(in, operation)
	if err != nil {
		return nil, err
	}
	meta, ok := payload["snapshot_meta"].(map[string]any)
	if !ok {
		return nil, errors.New("snapshot metadata missing")
	}
	meta["source_fingerprint"] = fingerprint
	meta["source_provenance"], err = sourceSummary(decisions.Sources)
	if err != nil {
		return nil, err
	}
	meta["safety_guard"] = decisions.SafetyGuard
	meta["knowledge"], err = knowledgeMetadata(route)
	if err != nil {
		return nil, err
	}
	content, err := coaching.CanonicalJSON(payload)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(content)
	tokens := (utf8.RuneCount(content) + route.Chars + 3) / 4
	var block struct {
		VersionID *uuid.UUID `json:"version_id"`
	}
	if err := json.Unmarshal(in.ActiveBlock, &block); err != nil {
		return nil, err
	}
	id := uuid.New()
	_, err = tx.Exec(ctx, `INSERT INTO coach_snapshots (id,operation,as_of,generated_at,calendar_version_number,block_version_id,
		data_revision,payload,source_fingerprint,source_versions,kb_digest,payload_sha256,kb_package_version,kb_routes,approx_tokens)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`, id, operation, asOf, now, in.CalendarVersion, block.VersionID,
		in.DataRevision, json.RawMessage(content), fingerprint, decisions.Sources, route.Knowledge.Digest, hex.EncodeToString(sum[:]), route.Version, route.Knowledge.Selection, tokens)
	if err != nil {
		return nil, err
	}
	return map[string]any{"snapshot_id": id.String(), "payload": payload, "kb": map[string]any{"package_version": route.Version, "excerpts": route.Excerpts}, "approx_tokens": tokens}, nil
}

func sourceSummary(s coaching.SourceVersions) (map[string]any, error) {
	content, err := coaching.CanonicalJSON(s)
	if err != nil {
		return nil, err
	}
	collections := map[string]any{}
	for key, val := range s {
		v := reflect.ValueOf(val)
		kind, count := "scalar", 1
		switch v.Kind() {
		case reflect.Map:
			kind, count = "object", v.Len()
		case reflect.Slice, reflect.Array:
			kind, count = "array", v.Len()
		case reflect.Invalid:
			count = 0
		}
		collections[key] = map[string]any{"kind": kind, "count": count}
	}
	return map[string]any{"sha256": fmt.Sprintf("%x", sha256.Sum256(content)), "collections": collections}, nil
}

func knowledgeMetadata(route coaching.Route) (map[string]any, error) {
	redundant := map[[3]string]bool{}
	for _, e := range route.Excerpts {
		id, ok := e["record_id"].(string)
		if !ok {
			continue
		}
		raw := []byte(e["text"].(string))
		if !json.Valid(raw) {
			continue
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var record any
		if err := decoder.Decode(&record); err != nil {
			return nil, err
		}
		encoded, err := coaching.CanonicalJSON(record)
		if err != nil {
			return nil, err
		}
		redundant[[3]string{e["path"].(string), id, string(encoded)}] = true
	}
	records := []map[string]any{}
	for _, r := range route.Knowledge.SelectedRecords {
		row := map[string]any{"path": r.Path, "record_id": r.RecordID}
		encoded, err := coaching.CanonicalJSON(r.Content)
		if err != nil {
			return nil, err
		}
		if !redundant[[3]string{r.Path, r.RecordID, string(encoded)}] {
			row["content"] = r.Content
		}
		records = append(records, row)
	}
	return map[string]any{"digest": route.Knowledge.Digest, "selected_records": records}, nil
}
