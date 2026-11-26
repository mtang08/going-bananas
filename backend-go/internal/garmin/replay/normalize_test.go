package replay

import (
	"bytes"
	"encoding/json"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"os"
	"testing"
	"time"
)

func equalJSON(t *testing.T, got, want any) {
	t.Helper()
	// Normalize Go typed numeric values and Python JSON tokens with the same
	// canonical encoder used to persist evidence; integer and float IDs differ.
	g, err := canonicaljson.Coaching(got)
	if err != nil {
		t.Fatal(err)
	}
	w, err := canonicaljson.Coaching(want)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(g, w) {
		t.Errorf("got %s\nwant %s", g, w)
	}
}

func TestActivityReference(t *testing.T) {
	data, err := os.ReadFile("testdata/activity-normalization.json")
	if err != nil {
		t.Fatal(err)
	}
	var corpus struct {
		Activities []struct {
			Name, Error string
			Record      map[string]any
			ProviderID  string `json:"provider_id"`
			Fields      map[string]any
		}
		Exports []struct {
			Name, Error, Owner string
			Archive            []byte
			MemberName         string `json:"member_name"`
			MemberCount        int    `json:"member_count"`
			ExpandedBytes      uint64 `json:"expanded_bytes"`
			ArchiveSHA         string `json:"archive_sha256"`
			Records            []struct {
				Record, Original map[string]any
				SHA              string `json:"member_sha256"`
				Index            int    `json:"row_index"`
			}
		}
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := dec.Decode(&corpus); err != nil {
		t.Fatal(err)
	}
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range corpus.Activities {
		t.Run("api/"+c.Name, func(t *testing.T) {
			got, err := Normalize(c.Record, zone)
			if c.Error != "" {
				if err == nil || err.Error() != c.Error {
					t.Fatalf("want %s; got %v", c.Error, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.ProviderID != c.ProviderID {
				t.Errorf("provider ID %q, want %q", got.ProviderID, c.ProviderID)
			}
			equalJSON(t, got.Fields, c.Fields)
		})
	}
	for _, c := range corpus.Exports {
		t.Run("export/"+c.Name, func(t *testing.T) {
			got, err := ScanExport(c.Archive)
			if c.Error != "" {
				if err == nil || err.Error() != c.Error {
					t.Fatalf("want %s; got %v", c.Error, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.Owner != c.Owner || got.MemberName != c.MemberName || got.MemberCount != c.MemberCount || got.ExpandedBytes != c.ExpandedBytes || len(got.Records) != len(c.Records) {
				t.Fatal("archive inventory or owner differs")
			}
			for i, r := range got.Records {
				w := c.Records[i]
				equalJSON(t, r.Record, w.Record)
				equalJSON(t, r.Original, w.Original)
				if r.Metadata["member_sha256"] != w.SHA || r.Metadata["archive_sha256"] != c.ArchiveSHA || r.Metadata["row_index"] != w.Index || r.Metadata["source_timezone"] != "garmin_export_GMT_epoch_ms" || r.Metadata["original_start"] != "1756000000125" {
					t.Error("source provenance differs")
				}
			}
		})
	}
}
