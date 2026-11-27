package snapshotreads

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

func TestProfileContract(t *testing.T) {
	tx := testpg.DashboardTx(t)
	ref := fixtureFile(t, "profile.json")
	var cases []struct {
		Facts    json.RawMessage
		Expected map[string]any
	}
	if err := json.Unmarshal(ref, &cases); err != nil {
		t.Fatal(err)
	}
	if _, err := tx.Exec(t.Context(), `CREATE TEMP TABLE profile_versions AS SELECT * FROM profile_versions WITH NO DATA;
		CREATE TEMP TABLE app_state AS SELECT * FROM app_state WITH NO DATA`); err != nil {
		t.Fatal(err)
	}
	for i, tc := range cases {
		if i == 1 {
			if _, err := tx.Exec(t.Context(), "INSERT INTO app_state(id,data_revision,calendar_head_version) VALUES(1,19,4)"); err != nil {
				t.Fatal(err)
			}
		}
		if i != 0 {
			if _, err := tx.Exec(t.Context(), `INSERT INTO profile_versions(version,timezone,cycle_anchor,anchor_confirmed,facts)
				VALUES($1,'America/Denver','2026-11-01',true,$2)`, i, tc.Facts); err != nil {
				t.Fatal(err)
			}
		}
		view, err := LoadProfile(t.Context(), tx, "2026-11-01")
		if tc.Expected == nil && err != nil {
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		data, err := json.Marshal(view)
		if err != nil {
			t.Fatal(err)
		}
		var actual map[string]any
		if err := json.Unmarshal(data, &actual); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(actual, tc.Expected) {
			t.Fatalf("case %d: got %v; want %v", i, actual, tc.Expected)
		}
	}
}
