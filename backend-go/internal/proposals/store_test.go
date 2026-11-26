package proposals_test

import (
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
)

// The integration runner loads backend/tests/fixtures/proposal-list.sql.
// This test reads it with a non-UTC session, independently of the machine zone.
func TestListPostgres(t *testing.T) {
	url := os.Getenv("PROPOSAL_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("requires PROPOSAL_TEST_DATABASE_URL and the proposal-list fixture")
	}
	ctx := t.Context()
	config, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal("invalid proposal test connection configuration")
	}
	if !strings.HasSuffix(config.ConnConfig.Database, "_test") {
		t.Fatal("proposal tests require a synthetic _test database")
	}
	config.ConnConfig.RuntimeParams["TimeZone"] = "Asia/Kathmandu"
	config.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	var name string
	if err := pool.QueryRow(ctx, "SELECT current_database()").Scan(&name); err != nil {
		t.Fatal(err)
	}
	if !strings.HasSuffix(name, "_test") {
		t.Fatal("expected to be connected to a synthetic _test database")
	}
	store := proposals.New(pool)
	for _, tc := range []struct {
		filter string
		count  int
		first  string
	}{
		{"", 50, "1"}, {"open", 1, "51"}, {"pending", 1, "51"},
		{"accepted", 48, "1"}, {"partially_accepted", 1, "50"},
		{"rejected", 1, "49"}, {"discarded", 1, "52"},
		{"stale", 0, ""}, {"invalid", 0, ""},
	} {
		t.Run("filter="+tc.filter, func(t *testing.T) {
			got, err := store.List(t.Context(), tc.filter)
			if err != nil {
				t.Fatal(err)
			}
			if got.DataRevision != 17 || got.Items == nil || len(got.Items) != tc.count {
				t.Fatalf("revision %d, count %d, nil items %v", got.DataRevision, len(got.Items), got.Items == nil)
			}
			if tc.count > 0 && got.Items[0].Headline != tc.first {
				t.Fatalf("first headline %q, want %q", got.Items[0].Headline, tc.first)
			}
			switch tc.filter {
			case "":
				first := got.Items[0]
				if first.ChangeCount != 0 || first.DecidedAt != nil || first.DiscardedAt != nil ||
					first.SubmittedAt.Format(time.RFC3339Nano) != "2026-01-02T05:45:00.1234+05:45" {
					t.Error("missing changes, nullable dates, or fractional session-local submission differ")
				}
				for i, item := range got.Items[1:] {
					if item.Headline != strconv.Itoa(51-i) || item.ChangeCount != 2 {
						t.Fatalf("unexpected tied row at index %d", i+1)
					}
				}
			case "partially_accepted":
				d := got.Items[0].DecidedAt
				if d == nil || d.Format(time.RFC3339Nano) != "2026-01-03T05:45:00.1234+05:45" {
					t.Error("unexpected decision timestamp")
				}
			case "discarded":
				d := got.Items[0].DiscardedAt
				if d == nil || d.Format(time.RFC3339Nano) != "2026-01-03T05:45:00+05:45" {
					t.Error("unexpected discard timestamp")
				}
			}
		})
	}
}
