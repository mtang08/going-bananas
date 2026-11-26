package drafts

import (
	"testing"
)

func TestPartition(t *testing.T) {
	d := Draft{Changes: map[string]Change{"c1": {ID: "c1", Operation: "modify"}, "c2": {ID: "c2", Operation: "add"}}}
	for _, tc := range []struct {
		accept, reject []string
		ok             bool
	}{
		{[]string{"c2"}, []string{"c1"}, true},
		{[]string{"c1", "c1"}, []string{"c2"}, false},
		{nil, []string{"c2"}, false},
		{[]string{"foreign"}, []string{"c1", "c2"}, false},
		{[]string{"c2"}, []string{"c1", "c2"}, false},
	} {
		selected, err := d.Partition(tc.accept, tc.reject)
		if (err == nil) != tc.ok {
			t.Fatalf("accept %v, reject %v: %v", tc.accept, tc.reject, err)
		}
		if tc.ok && (len(selected) != 1 || selected["c2"].Operation != "add") {
			t.Fatal("selection lost stored action")
		}
	}
}
