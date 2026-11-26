package trainingwindows

import (
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"reflect"
	"regexp"
	"testing"
	"time"
)

func TestAerobicWindowsPostgres(t *testing.T) {
	path := os.Getenv("AEROBIC_CASES")
	if path == "" {
		t.Skip("requires Python reference")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var ref struct {
		Query string
		Cases []struct {
			SQL   string
			State []map[string]any
		}
	}
	if err = json.Unmarshal(data, &ref); err != nil {
		t.Fatal(err)
	}
	ctx := t.Context()
	p, err := pgxpool.New(ctx, "")
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	cfg := p.Config().ConnConfig
	var schema string
	if (cfg.Host != "127.0.0.1" && cfg.Host != "localhost") || cfg.Database != "garmin_test" || p.QueryRow(ctx, "SELECT current_schema()").Scan(&schema) != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("expected isolated fixture")
	}
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	day := time.Date(2026, 3, 30, 0, 0, 0, 0, zone)
	for i, c := range ref.Cases {
		err = pgx.BeginFunc(ctx, p, func(tx pgx.Tx) error {
			if c.SQL != "" {
				if _, err := tx.Exec(ctx, c.SQL); err != nil {
					return err
				}
			}
			if err := RefreshAerobic(ctx, tx, day, day); err != nil {
				return err
			}
			var rows []map[string]any
			if err := tx.QueryRow(ctx, ref.Query).Scan(&rows); err != nil {
				return err
			}
			if len(rows) != len(c.State) {
				t.Fatalf("case %d row count %d vs %d", i, len(rows), len(c.State))
			}
			for j, row := range rows {
				for col, v := range row {
					if !reflect.DeepEqual(v, c.State[j][col]) {
						t.Fatalf("case %d row %d %s: %v vs %v", i, j, col, v, c.State[j][col])
					}
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}
