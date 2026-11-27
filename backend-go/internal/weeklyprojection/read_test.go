package weeklyprojection

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

// The saved projections cover empty, partial, and completed weeks across local day boundaries.
func TestWeeklyProjectionContract(t *testing.T) {
	tx := testpg.DashboardTx(t)
	output, err := os.ReadFile("testdata/expected.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Fixture    string
		Now        time.Time
		Projection map[string]any
	}
	if err := json.Unmarshal(output, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) != 5 {
		t.Fatal("incomplete projection fixture")
	}
	fixture := ""
	for _, c := range cases {
		if fixture != c.Fixture {
			fixture = c.Fixture
			raw, err := os.ReadFile("testdata/" + fixture)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := tx.Exec(t.Context(), string(raw)); err != nil {
				t.Fatal(err)
			}
		}
		p, err := Load(t.Context(), tx, c.Now)
		if err != nil {
			t.Fatal(err)
		}
		raw, err := json.Marshal(p)
		if err != nil {
			t.Fatal(err)
		}
		var got map[string]any
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, c.Projection) {
			t.Errorf("%s: got %+v, want %+v", c.Now, got, c.Projection)
		}
	}
}
