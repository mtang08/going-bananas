package calendar

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/matching/rematch"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
	"os"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestDerivedPostgres(t *testing.T) {
	path := os.Getenv("REMATCH_CASES")
	if path == "" {
		t.Skip("run scripts/test-db.py rematch")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name, SQL, Command string
		Scope              PlanScope
		Manual             bool
		UID                uuid.UUID
		Days               []string
		Clock              time.Time
		Matched            []string
		Counts             prompts.Counts
		State              map[string]any
	}
	if err = json.Unmarshal(raw, &cases); err != nil || len(cases) == 0 {
		t.Fatal("invalid reference", err)
	}
	ctx := t.Context()
	pool, err := pgxpool.New(ctx, "")
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	cfg := pool.Config().ConnConfig
	if (cfg.Host != "127.0.0.1" && cfg.Host != "localhost") || cfg.Database != "garmin_test" || pool.QueryRow(ctx, "SELECT current_schema()").Scan(&schema) != nil || !regexp.MustCompile("^go_parity_[a-f0-9]{32}$").MatchString(schema) {
		t.Fatal("expected isolated database")
	}
	for _, c := range cases {
		if !t.Run(c.Name, func(t *testing.T) {
			if c.Command == "plans" {
				calls := 0
				err := pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error {
					return RefreshPlans(ctx, tx, c.Scope, c.Clock, func(ctx context.Context, tx pgx.Tx, scope PlanScope, matched []uuid.UUID) error {
						calls++
						ids := make([]string, len(matched))
						for i, id := range matched {
							ids[i] = id.String()
						}
						if !slices.Equal(scope.Dates, c.Days) || !slices.Equal(ids, c.Matched) {
							return fmt.Errorf("scope %v / %v, reference %v / %v", scope.Dates, ids, c.Days, c.Matched)
						}
						return nil
					})
				})
				if err != nil || (calls == 0) != (c.Name == "revision-only") {
					t.Fatal("scope refresh", calls, err)
				}
			} else if c.Command != "" {
				refresh := DerivedRefresh(c.Clock, func(ctx context.Context, tx pgx.Tx, target CompletionTargets) error {
					var matched []string
					for _, id := range target.Matched {
						matched = append(matched, id.String())
					}
					if c.Manual != target.ManualOnly || !slices.Equal(c.Days, target.Dates) || !slices.Equal(c.Matched, matched) {
						return fmt.Errorf("different scope: %+v vs %v %v %v", target, c.Manual, c.Days, c.Matched)
					}
					return nil
				})
				var err error
				if c.Command == "integrated self report" {
					_, err = SaveSelfReport(ctx, pool, c.UID, SelfReport{Status: CompletedAsPlanned}, c.Clock, refresh)
				} else {
					manual := uuid.MustParse("00000000-0000-0000-0000-000000000051")
					_, err = SaveRecordingLink(ctx, pool, c.UID, RecordingLink{ExpectedVersion: 1, ManualSessionID: &manual}, c.Clock, func(context.Context, pgx.Tx, uuid.UUID) error { return nil }, refresh)
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			err := pgx.BeginFunc(ctx, pool, func(tx pgx.Tx) error {
				for _, statement := range strings.Split(c.SQL, ";") {
					if strings.TrimSpace(statement) != "" {
						if _, err := tx.Exec(ctx, statement); err != nil {
							return err
						}
					}
				}
				if c.Command == "" {
					ids, err := rematch.Dates(ctx, tx, c.Days, c.Clock)
					if err != nil {
						return err
					}
					got := make([]string, 0, len(ids))
					for _, id := range ids {
						got = append(got, id.String())
					}
					if !slices.Equal(got, c.Matched) {
						return fmt.Errorf("affected IDs %v, reference %v", got, c.Matched)
					}
					counts, err := prompts.Generate(ctx, tx, c.Clock)
					if err != nil {
						return err
					}
					if counts != c.Counts {
						return fmt.Errorf("prompt counts %+v, reference %+v", counts, c.Counts)
					}
				}
				var state map[string]any
				if err := tx.QueryRow(ctx, `SELECT jsonb_build_object('completions',coalesce((SELECT jsonb_agg(to_jsonb(c)-'id'-'updated_at' ORDER BY session_uid) FROM session_completions c),'[]'),
     'prompts',coalesce((SELECT jsonb_agg(to_jsonb(p)-'id' ORDER BY kind,coalesce(activity_id,session_uid)) FROM prompts p),'[]'))`).Scan(&state); err != nil {
					return err
				}
				if !reflect.DeepEqual(state, c.State) {
					return fmt.Errorf("state %v, reference %v", state, c.State)
				}
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
		}) {
			return
		}
	}
}
