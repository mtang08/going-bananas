package checkins

import (
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestRefreshScopesAcrossMidnightAndDST(t *testing.T) {
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	id, activity := uuid.New(), uuid.New()
	old := View{ID: id, ObservedAt: "2027-03-14T04:30:00+00:00", ActivityID: &activity}
	newer := View{ID: id, ObservedAt: "2027-03-15T04:30:00+00:00"}
	got, err := scopes(zone, old, newer)
	want := []string{"activity:" + activity.String(), "checkin:" + id.String(), "date:2027-03-11", "date:2027-03-12", "date:2027-03-13", "date:2027-03-14", "date:2027-03-15", "recovery_dates:2027-03-13", "recovery_dates:2027-03-15"}
	if err != nil || !slices.Equal(got, want) {
		t.Fatal(got, err)
	}
}

func TestSymptomsFollowPythonOrdinalIDs(t *testing.T) {
	id := uuid.MustParse("ffffffff-aabb-4abc-8abc-ffffffffff11")
	if got := symptomID(id, 257).String(); got != "0101ffff-aabb-4abc-8abc-ffffffffff11" {
		t.Fatal(got)
	}
}
