package coachdashboard

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// ImportPythonFiles runs at cutover, before serving the mode. The state and turn
// locks also protect a running Python writer. Original files remain on disk.
func (s *Store) ImportPythonFiles(ctx context.Context, privateDir string) error {
	if !filepath.IsLocal(s.mode) || filepath.Base(s.mode) != s.mode || s.mode == "." {
		return errors.New("invalid dashboard mode")
	}
	root, err := os.OpenRoot(filepath.Join(privateDir, "coach-chat", s.mode))
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer func() { _ = root.Close() }()
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, stateLock, s.mode); err != nil {
			return err
		}
		var imported bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM coach_chat_file_imports WHERE mode=$1)", s.mode).Scan(&imported); err != nil || imported {
			return err
		}
		for _, name := range []string{"state.lock", "turn.lock"} {
			lock, err := root.OpenFile(name, os.O_RDWR|os.O_CREATE, 0600)
			if err != nil {
				return err
			}
			defer func() { _ = lock.Close() }()
			if err := syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
				return fmt.Errorf("dashboard file store is busy: %w", err)
			}
		}
		if err := s.importLocked(ctx, tx, root); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, "INSERT INTO coach_chat_file_imports(mode) VALUES ($1)", s.mode)
		return err
	})
}

func (s *Store) importLocked(ctx context.Context, tx pgx.Tx, root *os.Root) error {
	var state struct {
		Review   json.RawMessage   `json:"review"`
		Receipts map[string]string `json:"receipts"`
	}
	data, err := root.ReadFile("state.json")
	if err == nil {
		if err = json.Unmarshal(data, &state); err != nil {
			return err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	archives, err := fs.ReadDir(root.FS(), "reviews")
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	if len(state.Review) == 0 && len(state.Receipts) == 0 && len(archives) == 0 {
		return nil
	}
	var occupied bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM coach_chat_reviews WHERE mode=$1)
		OR EXISTS(SELECT FROM coach_chat_receipts WHERE mode=$1)`, s.mode).Scan(&occupied); err != nil {
		return err
	}
	if occupied {
		return errors.New("dashboard already has conversation data; resolve the cutover before importing files")
	}
	currentID, err := s.importReview(ctx, tx, state.Review, "", true)
	if err != nil {
		return err
	}
	for _, entry := range archives {
		id, ok := strings.CutSuffix(entry.Name(), ".json")
		if !ok || id == currentID {
			continue
		}
		raw, err := root.ReadFile(filepath.Join("reviews", entry.Name()))
		if err != nil {
			return err
		}
		if _, err = s.importReview(ctx, tx, raw, id, false); err != nil {
			return err
		}
	}
	for id, digest := range state.Receipts {
		value, err := hex.DecodeString(digest)
		if uuid.Validate(id) != nil || err != nil || len(value) != 32 {
			return errors.New("invalid Python message receipt")
		}
		if _, err := tx.Exec(ctx, "INSERT INTO coach_chat_receipts(mode,client_message_id,digest) VALUES($1,$2,$3)", s.mode, id, digest); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) importReview(ctx context.Context, tx pgx.Tx, raw json.RawMessage, archiveID string, current bool) (string, error) {
	if len(raw) == 0 && current {
		return "", nil
	}
	var r Review
	if err := json.Unmarshal(raw, &r); err != nil {
		return "", err
	}
	if current && r.ID == "" && r.Status == "idle" && len(r.Messages) == 0 {
		return "", nil
	}
	if uuid.Validate(r.ID) != nil || (!current && r.ID != archiveID) {
		return "", errors.New("invalid Python review ID")
	}
	switch r.Status {
	case "idle", "cancelled", "failed", "running":
	default:
		return "", errors.New("invalid Python review status")
	}
	// Store the full JSON, retaining tool context and private resume IDs. Store.load
	// recovers an interrupted running turn once PostgreSQL owns the review.
	_, err := tx.Exec(ctx, "INSERT INTO coach_chat_reviews(mode,id,state,current) VALUES($1,$2,$3,$4)", s.mode, r.ID, raw, current)
	return r.ID, err
}
