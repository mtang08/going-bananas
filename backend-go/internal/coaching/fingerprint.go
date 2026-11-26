package coaching

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

// SourceVersions is the open-ended snapshot evidence object. All supplied keys,
// including legacy evidence, participate in draft freshness.
type SourceVersions map[string]any

// RecordContent holds the entire verified record, including fields unused by
// the compact coaching display.
type RecordContent map[string]any

func (s *SourceVersions) UnmarshalJSON(data []byte) error {
	return decodeEvidenceObject(data, (*map[string]any)(s))
}

func (c *RecordContent) UnmarshalJSON(data []byte) error {
	return decodeEvidenceObject(data, (*map[string]any)(c))
}

func decodeEvidenceObject(data []byte, target *map[string]any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var object map[string]any
	if err := decoder.Decode(&object); err != nil {
		return err
	}
	*target = object
	return nil
}

// SelectionEntry identifies either sections or record IDs in their supplied
// order. The unused slice is nil in a verified selection.
type SelectionEntry struct {
	Path      string   `json:"path"`
	Sections  []string `json:"sections,omitempty"`
	RecordIDs []string `json:"record_ids,omitempty"`
}

type SelectedRecord struct {
	Path     string        `json:"path"`
	RecordID string        `json:"record_id"`
	Content  RecordContent `json:"content"`
}

// VerifiedKnowledge is the fingerprint-relevant output of knowledge verification.
type VerifiedKnowledge struct {
	Digest          string           `json:"digest"`
	Selection       []SelectionEntry `json:"selection"`
	SelectedRecords []SelectedRecord `json:"selected_records"`
}

// Fingerprint returns the exact canonical evidence bytes and their lowercase SHA-256.
func Fingerprint(sources SourceVersions, kb VerifiedKnowledge) ([]byte, string, error) {
	selection := make([]any, len(kb.Selection))
	for i, entry := range kb.Selection {
		item := map[string]any{"path": entry.Path}
		if entry.Sections != nil {
			item["sections"] = entry.Sections
		}
		if entry.RecordIDs != nil {
			item["record_ids"] = entry.RecordIDs
		}
		selection[i] = item
	}
	records := make([]any, len(kb.SelectedRecords))
	for i, record := range kb.SelectedRecords {
		records[i] = map[string]any{"path": record.Path, "record_id": record.RecordID, "content": record.Content}
	}
	vector := map[string]any{
		"source_versions": sources,
		"knowledge":       map[string]any{"digest": kb.Digest, "selection": selection, "selected_records": records},
	}
	canonical, err := CanonicalJSON(vector)
	if err != nil {
		return nil, "", err
	}
	hash := sha256.Sum256(canonical)
	return canonical, hex.EncodeToString(hash[:]), nil
}
