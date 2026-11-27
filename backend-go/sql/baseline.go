// Package baseline embeds the PostgreSQL schema and bootstrap data generated from a fresh migration.
package baseline

import (
	_ "embed"
	"encoding/json"
	"strings"
)

//go:embed schema.sql
var ddl string

//go:embed bootstrap.sql
var bootstrap string

// SQL targets the transaction's selected workspace schema. pg_dump qualifies its
// table names and regclass literals with public; the caller sets a local search_path.
func SQL() string {
	script := strings.ReplaceAll(ddl, "SELECT pg_catalog.set_config('search_path', '', false);", "")
	data := strings.NewReplacer("INSERT INTO public.", "INSERT INTO ", "SELECT pg_catalog.setval('public.", "SELECT pg_catalog.setval('").Replace(bootstrap)
	return strings.ReplaceAll(script, "public.", "") + data
}

//go:embed revisions.json
var revisionsJSON []byte

// Revisions is the linear Alembic lineage from the same checkout as the baseline.
func Revisions() []string {
	var ids []string
	if err := json.Unmarshal(revisionsJSON, &ids); err != nil || len(ids) == 0 {
		panic("invalid embedded revision history")
	}
	return ids
}
