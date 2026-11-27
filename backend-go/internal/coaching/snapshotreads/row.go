package snapshotreads

import (
	"bytes"
	"encoding/json"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

// Keep integer and floating JSON values distinct, as the Python ORM does.
// Their distinction participates in the persisted snapshot's canonical hash.
func snapshotRow(row pgx.CollectableRow) (map[string]any, error) {
	fields := row.FieldDescriptions()
	value, err := pgx.RowToMap(row)
	if err != nil {
		return nil, err
	}
	for i, f := range fields {
		if f.DataTypeOID != pgtype.JSONBOID && f.DataTypeOID != pgtype.JSONOID {
			continue
		}
		raw := row.RawValues()[i]
		if raw == nil {
			continue
		}
		if f.DataTypeOID == pgtype.JSONBOID && f.Format == pgx.BinaryFormatCode {
			raw = raw[1:]
		}
		dec := json.NewDecoder(bytes.NewReader(raw))
		dec.UseNumber()
		var v any
		if err := dec.Decode(&v); err != nil {
			return nil, err
		}
		value[f.Name] = v
	}
	return value, nil
}
