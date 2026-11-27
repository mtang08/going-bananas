package snapshots

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestPreparedSnapshotPersistence(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable dashboard PostgreSQL runner")
	}
	ops := []string{daily, rolling, blockReview, quality, race, calibrate, exception, postEvent}
	args := append([]string{"testdata/build_reference.py"}, ops...)
	output, err := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), args...).Output()
	if err != nil {
		t.Fatal("Python prepared snapshot reference:", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(output))
	ctx := t.Context()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("open snapshot fixture")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if _, err := tx.Exec(ctx, "SET LOCAL TIME ZONE 'UTC'"); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2030, 1, 9, 18, 30, 0, 0, time.UTC)
	const kb = "../../../../running_coach_kb"
	// A preparation error rolls back its writes, even if the caller catches the error and commits.
	if _, err := tx.Exec(ctx, "CREATE TEMP TABLE snapshot_prepare_probe(value int)"); err != nil {
		t.Fatal(err)
	}
	stop := errors.New("test failure after write")
	_, err = BuildWithPreparation(ctx, tx, daily, "2030-01-09", now, kb, func(ctx context.Context, tx pgx.Tx, _, _ string, _ time.Time) error {
		if _, err := tx.Exec(ctx, "INSERT INTO snapshot_prepare_probe VALUES (1)"); err != nil {
			return err
		}
		return stop
	})
	if !errors.Is(err, stop) {
		t.Fatal(err)
	}
	// A failure after successful preparation must also unwind that preparation.
	_, err = BuildWithPreparation(ctx, tx, daily, "2030-01-09", now, t.TempDir(), func(ctx context.Context, tx pgx.Tx, _, _ string, _ time.Time) error {
		_, err := tx.Exec(ctx, "INSERT INTO snapshot_prepare_probe VALUES (2)")
		return err
	})
	if err == nil {
		t.Fatal("missing KB package should fail after preparation")
	}
	var count int
	if err := tx.QueryRow(ctx, "SELECT count(*) FROM snapshot_prepare_probe").Scan(&count); err != nil || count != 0 {
		t.Fatal("failed preparation leaked effects", err)
	}
	for _, op := range ops {
		t.Run(op, func(t *testing.T) {
			var want struct {
				PayloadCanonical string `json:"payload_canonical"`
				Packet           map[string]any
				PayloadSHA       string         `json:"payload_sha256"`
				Sources          map[string]any `json:"source_versions"`
			}
			if err := decoder.Decode(&want); err != nil {
				t.Fatal(err)
			}
			output, err := BuildWithPreparation(ctx, tx, op, "2030-01-09", now, kb, func(context.Context, pgx.Tx, string, string, time.Time) error { return nil })
			if err != nil {
				t.Fatal(err)
			}
			var stored struct {
				Payload, Sources map[string]any
				SHA              string
			}
			err = tx.QueryRow(ctx, "SELECT payload,source_versions,payload_sha256 FROM coach_snapshots WHERE id=$1", output["snapshot_id"]).Scan(&stored.Payload, &stored.Sources, &stored.SHA)
			if err != nil {
				t.Fatal(err)
			}
			snapshotID := output["snapshot_id"]
			delete(output, "snapshot_id")
			b, err := json.Marshal(output)
			if err != nil {
				t.Fatal(err)
			}
			var got map[string]any
			if err := json.Unmarshal(b, &got); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(stored.Payload, got["payload"]) {
				t.Fatal("persisted payload differs from output")
			}
			for _, v := range []struct {
				name      string
				got, want any
			}{{"sources", stored.Sources, want.Sources}, {"packet", got, want.Packet}} {
				if diff := firstDifference(v.name, v.got, v.want); diff != "" {
					t.Error(diff)
				}
			}
			if stored.SHA != want.PayloadSHA {
				var dbJSON []byte
				if err := tx.QueryRow(ctx, "SELECT payload FROM coach_snapshots WHERE id=$1", snapshotID).Scan(&dbJSON); err != nil {
					t.Fatal(err)
				}
				var actual, wanted any
				for _, v := range []struct {
					b    []byte
					dest *any
				}{{dbJSON, &actual}, {[]byte(want.PayloadCanonical), &wanted}} {
					d := json.NewDecoder(bytes.NewReader(v.b))
					d.UseNumber()
					if err := d.Decode(v.dest); err != nil {
						t.Fatal(err)
					}
				}
				t.Errorf("stored SHA %s; Python %s: %s", stored.SHA, want.PayloadSHA, firstDifference("payload", actual, wanted))
			}
		})
	}
}

func firstDifference(path string, got, want any) string {
	if reflect.DeepEqual(got, want) {
		return ""
	}
	switch w := want.(type) {
	case map[string]any:
		if g, ok := got.(map[string]any); ok {
			for k, v := range w {
				if d := firstDifference(path+"."+k, g[k], v); d != "" {
					return d
				}
			}
		}
	case []any:
		if g, ok := got.([]any); ok && len(g) == len(w) {
			for i, v := range w {
				if d := firstDifference(fmt.Sprintf("%s[%d]", path, i), g[i], v); d != "" {
					return d
				}
			}
		}
	}
	return fmt.Sprintf("%s differs: got %.320v, want %.320v", path, got, want)
}

// Replay the native preparation over Python-prepared state. Correct idempotent
// derivations retain metric result IDs and evidence fingerprints.
func TestProductionSnapshotReplay(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable dashboard PostgreSQL runner")
	}
	ctx := t.Context()
	r, err := exec.CommandContext(ctx, os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/build_reference.py", "--native", rolling).Output()
	if err != nil {
		t.Fatal("Python preparation failed:", err)
	}
	var want struct {
		Packet  map[string]any
		Sources map[string]any `json:"source_versions"`
		SHA     string         `json:"payload_sha256"`
	}
	if err := json.Unmarshal(r, &want); err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("connect to snapshot replay fixture")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if _, err = tx.Exec(ctx, "SET LOCAL TIME ZONE 'UTC'"); err != nil {
		t.Fatal(err)
	}
	out, err := Build(ctx, tx, rolling, "2030-01-09", time.Date(2030, 1, 9, 18, 30, 0, 0, time.UTC), "../../../../running_coach_kb")
	if err != nil {
		t.Fatal(err)
	}
	var sources, payload map[string]any
	var sha string
	if err := tx.QueryRow(ctx, "SELECT source_versions,payload,payload_sha256 FROM coach_snapshots WHERE id=$1", out["snapshot_id"]).Scan(&sources, &payload, &sha); err != nil {
		t.Fatal(err)
	}
	if d := firstDifference("prepared sources", sources, want.Sources); d != "" {
		t.Error(d)
	}
	if d := firstDifference("prepared payload", payload, want.Packet["payload"]); d != "" {
		t.Error(d)
	}
	if sha != want.SHA {
		t.Error("production payload hash differs from Python")
	}
}
