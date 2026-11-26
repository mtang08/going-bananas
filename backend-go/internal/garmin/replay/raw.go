// Package replay imports previously fetched Garmin observations into the local data model.
package replay

import (
	"context"
	"crypto/sha256"
	"fmt"
	"path/filepath"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/rawobject"
)

type object struct {
	Hash, Path, Media string
	Size              int
}

func digest(b []byte) string { return fmt.Sprintf("%x", sha256.Sum256(b)) }

// Write immutable bytes before their referencing transaction. A retry can reuse
// an unreferenced file left by a rollback, but cannot replace another payload.
func retain(root, kind string, b []byte) (object, error) {
	hash := digest(b)
	path := filepath.Join("raw", hash[:2], hash+".json")
	media := "application/json"
	switch kind {
	case "fit":
		path = filepath.Join("raw", "fit", hash[:2], hash+".zip")
		media = "application/zip"
	case "export":
		path = filepath.Join("raw", "archives", hash+".zip")
		media = "application/zip"
	}
	o := object{hash, path, media, len(b)}
	return o, rawobject.Write(root, path, b)
}

func (o object) persist(ctx context.Context, tx pgx.Tx) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `WITH added AS (
		INSERT INTO raw_objects(id, sha256, relative_path, byte_size, media_type)
		VALUES(gen_random_uuid(),$1,$2,$3,$4) ON CONFLICT(sha256) DO NOTHING RETURNING id)
		SELECT id FROM added UNION ALL SELECT id FROM raw_objects WHERE sha256=$1 LIMIT 1`,
		o.Hash, o.Path, o.Size, o.Media).Scan(&id)
	return id, err
}
