// Package replay imports previously fetched Garmin observations into the local data model.
package replay

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
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
	target := filepath.Join(root, path)
	dir := filepath.Dir(target)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return o, err
	}
	existing, err := os.ReadFile(target)
	if errors.Is(err, os.ErrNotExist) {
		tmp, err := os.CreateTemp(dir, ".raw-*")
		if err != nil {
			return o, err
		}
		defer func() { _ = os.Remove(tmp.Name()) }()
		if _, err = tmp.Write(b); err == nil {
			err = tmp.Sync()
		}
		closeErr := tmp.Close()
		if err != nil {
			return o, err
		}
		if closeErr != nil {
			return o, closeErr
		}
		if err = os.Link(tmp.Name(), target); err != nil && !errors.Is(err, os.ErrExist) {
			return o, err
		}
		existing, err = os.ReadFile(target)
		if err != nil {
			return o, err
		}
	} else if err != nil {
		return o, err
	}
	if !bytes.Equal(existing, b) {
		return o, errors.New("raw_hash_mismatch")
	}
	return o, nil
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
