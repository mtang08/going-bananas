package snapshots

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

func snapshotTestTx(t *testing.T) pgx.Tx {
	t.Helper()
	tx := testpg.DashboardTx(t)
	if _, err := tx.Exec(t.Context(), "SET LOCAL TIME ZONE 'UTC'"); err != nil {
		t.Fatal(err)
	}
	return tx
}

func TestPreparedSnapshotPersistence(t *testing.T) {
	tx := snapshotTestTx(t)
	ctx := t.Context()
	raw, err := os.ReadFile("testdata/prepared.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Operation        string
		PayloadSHA       string `json:"payload_sha256"`
		SourcesSHA       string `json:"source_versions_sha256"`
		ApproxTokens     int    `json:"approx_tokens"`
		KBPackageVersion string `json:"kb_package_version"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) != 8 {
		t.Fatal("missing prepared snapshot operations")
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
	for _, want := range cases {
		t.Run(want.Operation, func(t *testing.T) {
			output, err := BuildWithPreparation(ctx, tx, want.Operation, "2030-01-09", now, kb, func(context.Context, pgx.Tx, string, string, time.Time) error { return nil })
			if err != nil {
				t.Fatal(err)
			}
			var payload, sources json.RawMessage
			var storedSHA, kbVersion string
			var storedTokens int
			err = tx.QueryRow(ctx, "SELECT payload,source_versions,payload_sha256,kb_package_version,approx_tokens FROM coach_snapshots WHERE id=$1",
				output["snapshot_id"]).Scan(&payload, &sources, &storedSHA, &kbVersion, &storedTokens)
			if err != nil {
				t.Fatal(err)
			}
			var got any
			if err := json.Unmarshal(payload, &got); err != nil {
				t.Fatal(err)
			}
			responseJSON, err := json.Marshal(output["payload"])
			if err != nil {
				t.Fatal(err)
			}
			var response any
			if err := json.Unmarshal(responseJSON, &response); err != nil {
				t.Fatal(err)
			}
			if d := firstDifference("persisted payload", got, response); d != "" {
				t.Error(d)
			}
			var sourceValue any
			decoder := json.NewDecoder(bytes.NewReader(sources))
			decoder.UseNumber()
			if err := decoder.Decode(&sourceValue); err != nil {
				t.Fatal(err)
			}
			canonical, err := coaching.CanonicalJSON(sourceValue)
			if err != nil {
				t.Fatal(err)
			}
			if hash := fmt.Sprintf("%x", sha256.Sum256(canonical)); hash != want.SourcesSHA {
				t.Errorf("source versions digest: got %s, want %s", hash, want.SourcesSHA)
			}
			if storedSHA != want.PayloadSHA || kbVersion != want.KBPackageVersion || storedTokens != want.ApproxTokens {
				t.Errorf("persisted payload digest, KB version, tokens: got %s %s %d, want %s %s %d",
					storedSHA, kbVersion, storedTokens, want.PayloadSHA, want.KBPackageVersion, want.ApproxTokens)
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

// Repeating native preparation on identical inputs must preserve metric row IDs
// and must persist another snapshot with the same evidence identity and payload.
func TestProductionSnapshotReplay(t *testing.T) {
	tx := snapshotTestTx(t)
	ctx := t.Context()
	now := time.Date(2030, 1, 9, 18, 30, 0, 0, time.UTC)
	type persisted struct {
		ID               string
		Sources, Payload map[string]any
		SHA, Fingerprint string
		MetricIDs        []uuid.UUID
	}
	build := func() persisted {
		t.Helper()
		out, err := Build(ctx, tx, rolling, "2030-01-09", now, "../../../../running_coach_kb")
		if err != nil {
			t.Fatal(err)
		}
		id, ok := out["snapshot_id"].(string)
		if !ok || id == "" {
			t.Fatal("missing persisted snapshot ID")
		}
		result := persisted{ID: id}
		err = tx.QueryRow(ctx, `SELECT source_versions,payload,payload_sha256,source_fingerprint,
			(SELECT coalesce(array_agg(id ORDER BY id),'{}') FROM metric_results)
			FROM coach_snapshots WHERE id=$1`, id).Scan(&result.Sources, &result.Payload, &result.SHA, &result.Fingerprint, &result.MetricIDs)
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	first, replay := build(), build()
	if replay.ID == first.ID || replay.SHA != first.SHA || replay.Fingerprint != first.Fingerprint {
		t.Fatal("expected separate snapshot rows with the same evidence and payload digests")
	}
	if d := firstDifference("prepared sources", replay.Sources, first.Sources); d != "" {
		t.Error(d)
	}
	if d := firstDifference("prepared payload", replay.Payload, first.Payload); d != "" {
		t.Error(d)
	}
	if len(first.MetricIDs) == 0 {
		t.Fatal("production preparation did not persist metric results")
	}
	if !slices.Equal(replay.MetricIDs, first.MetricIDs) {
		t.Error("replay changed persisted metric rows")
	}
}
