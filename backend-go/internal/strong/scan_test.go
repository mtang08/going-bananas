package strong

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

func TestPythonCSV(t *testing.T) {
	b, err := os.ReadFile("testdata/scan.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name, CSV, Digest, Error string
		Workouts                 []Workout
	}
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			got, err := scan([]byte(tc.CSV), maxRows)
			if tc.Error != "" {
				if err == nil || err.Error() != tc.Error {
					t.Fatalf("error = %v, want %s", err, tc.Error)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.Digest != tc.Digest || !reflect.DeepEqual(got.Workouts, tc.Workouts) {
				t.Errorf("Python mismatch: %+v", got.Workouts)
			}
		})
	}
}
