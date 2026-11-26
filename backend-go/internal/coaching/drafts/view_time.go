package drafts

import (
	"encoding/json"
	"github.com/mtang08/going-bananas/backend-go/api"
	"time"
)

// PostgreSQL's jsonb timestamp renderer trims insignificant fractional digits.
// FastAPI timestamps keep all six microseconds whenever the fraction is nonzero.
func viewTimes(row map[string]json.RawMessage, fields ...string) error {
	for _, key := range fields {
		raw := row[key]
		if !has(raw) {
			continue
		}
		var instant time.Time
		if err := json.Unmarshal(raw, &instant); err != nil {
			return err
		}
		encoded, err := json.Marshal(api.Timestamp(instant))
		if err != nil {
			return err
		}
		row[key] = encoded
	}
	return nil
}
func timedRow(raw json.RawMessage, fields ...string) (json.RawMessage, error) {
	if !has(raw) {
		return raw, nil
	}
	var row map[string]json.RawMessage
	if err := json.Unmarshal(raw, &row); err != nil {
		return nil, err
	}
	if err := viewTimes(row, fields...); err != nil {
		return nil, err
	}
	return json.Marshal(row)
}
func timedRows(raw json.RawMessage, fields ...string) (json.RawMessage, error) {
	var rows []map[string]json.RawMessage
	if err := json.Unmarshal(raw, &rows); err != nil {
		return nil, err
	}
	for _, row := range rows {
		if err := viewTimes(row, fields...); err != nil {
			return nil, err
		}
	}
	return json.Marshal(rows)
}
