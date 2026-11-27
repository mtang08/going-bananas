package replay

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

// DemoActivity uses the importer's normal source normalization and reconciliation,
// without creating a provider import batch or a pending treadmill review.
func DemoActivity(ctx context.Context, tx pgx.Tx, root string, account uuid.UUID, row map[string]any, zone *time.Location, now time.Time) (uuid.UUID, error) {
	n, err := Normalize(row, zone)
	if err != nil {
		return uuid.Nil, err
	}
	body, err := canonicaljson.Coaching(row)
	if err != nil {
		return uuid.Nil, err
	}
	obj, err := retain(root, "json", body)
	if err != nil {
		return uuid.Nil, err
	}
	raw, err := obj.persist(ctx, tx)
	if err != nil {
		return uuid.Nil, err
	}
	identity := "garmin:" + n.ProviderID
	tag, err := tx.Exec(ctx, `INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields) VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,'garmin-personal-v1','demo_fixture',$6) ON CONFLICT(source_account_id,source_identity,payload_hash) DO NOTHING`, account, raw, identity, obj.Hash, now, n.Fields)
	if err != nil {
		return uuid.Nil, err
	}
	if tag.RowsAffected() == 0 {
		var id uuid.UUID
		err := tx.QueryRow(ctx, "SELECT id FROM activities WHERE source_account_id=$1 AND source_identity=$2", account, identity).Scan(&id)
		return id, err
	}
	id, _, _, err := reconcile(ctx, tx, account, identity, n.ProviderID, &Result{})
	return id, err
}
