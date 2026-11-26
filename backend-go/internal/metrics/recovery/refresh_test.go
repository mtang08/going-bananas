package recovery

import (
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestRecoveryPostgres(t *testing.T) {
	path := os.Getenv("RECOVERY_CASES")
	if path == "" {
		t.Skip("requires Python recovery fixture")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var ref struct {
		Query string
		Cases []struct {
			SQL   string
			Keys  []string
			State map[string]any
		}
	}
	if err := json.Unmarshal(raw, &ref); err != nil {
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
	if (cfg.Host != "localhost" && cfg.Host != "127.0.0.1") || cfg.Database != "garmin_test" || p.QueryRow(ctx, "SELECT current_schema()").Scan(&schema) != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("requires isolated test schemas")
	}
	for i, c := range ref.Cases {
		err = pgx.BeginFunc(ctx, p, func(tx pgx.Tx) error {
			for _, s := range strings.Split(c.SQL, ";") {
				if strings.TrimSpace(s) != "" {
					if _, err := tx.Exec(ctx, s); err != nil {
						return err
					}
				}
			}
			for _, key := range c.Keys {
				if _, err := Refresh(ctx, tx, key, time.Now()); err != nil {
					return err
				}
			}
			var state map[string]any
			if err := tx.QueryRow(ctx, ref.Query).Scan(&state); err != nil {
				return err
			}
			if !reflect.DeepEqual(state, c.State) {
				for k, v := range state {
					rows := v.([]any)
					wants := c.State[k].([]any)
					if len(rows) != len(wants) {
						t.Fatalf("case %d %s: %d rows vs %d", i, k, len(rows), len(wants))
					}
					for j, x := range rows {
						for col, val := range x.(map[string]any) {
							if !reflect.DeepEqual(val, wants[j].(map[string]any)[col]) {
								t.Fatalf("case %d %s[%d].%s: %v vs %v", i, k, j, col, val, wants[j].(map[string]any)[col])
							}
						}
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
