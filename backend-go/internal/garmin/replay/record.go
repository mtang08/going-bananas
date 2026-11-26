package replay

// ActivityRecord keeps the original export bytes reproducible alongside their API-shaped input and provenance.
type ActivityRecord struct {
	Record   map[string]any
	Original map[string]any
	Metadata map[string]any
}
