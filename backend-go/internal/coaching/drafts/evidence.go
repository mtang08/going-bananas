package drafts

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

type Snapshot struct {
	ID          uuid.UUID                 `json:"id"`
	Operation   string                    `json:"operation"`
	AsOf        string                    `json:"as_of"`
	GeneratedAt time.Time                 `json:"generated_at"`
	Fingerprint string                    `json:"source_fingerprint"`
	KBDigest    string                    `json:"kb_digest"`
	Sources     coaching.SourceVersions   `json:"source_versions"`
	Selection   []coaching.SelectionEntry `json:"kb_selection"`
}

func LoadSnapshot(ctx context.Context, tx pgx.Tx, id uuid.UUID) (Snapshot, error) {
	var s Snapshot
	var routes json.RawMessage
	err := tx.QueryRow(ctx, `SELECT id,operation,to_char(as_of,'YYYY-MM-DD'),generated_at,source_fingerprint,kb_digest,source_versions,kb_routes
	FROM coach_snapshots WHERE id=$1`, id).Scan(&s.ID, &s.Operation, &s.AsOf, &s.GeneratedAt, &s.Fingerprint, &s.KBDigest, &s.Sources, &routes)
	if errors.Is(err, pgx.ErrNoRows) {
		return Snapshot{}, &Error{"snapshot_not_found", "Snapshot not found", 404}
	}
	if err != nil {
		return Snapshot{}, err
	}
	if bytes.HasPrefix(bytes.TrimSpace(routes), []byte("{")) {
		var legacy struct {
			Selection []coaching.SelectionEntry `json:"selection"`
		}
		if err := json.Unmarshal(routes, &legacy); err != nil {
			return Snapshot{}, err
		}
		s.Selection = legacy.Selection
	} else if err := json.Unmarshal(routes, &s.Selection); err != nil {
		return Snapshot{}, err
	}
	return s, nil
}

type DocumentBase struct {
	Operation       string     `json:"operation"`
	SnapshotID      uuid.UUID  `json:"snapshot_id"`
	CalendarVersion int        `json:"base_calendar_version"`
	BlockVersion    *uuid.UUID `json:"base_block_version_id"`
}

type CurrentEvidence struct {
	Today   string                  `json:"today"`
	Head    int                     `json:"head"`
	BlockID *uuid.UUID              `json:"block_id"`
	Sources coaching.SourceVersions `json:"sources"`
}

func staleIssue(code, path string) Issue { return Issue{code, path, code} }

// Freshness checks the saved evidence and the current facts under the writer's
// snapshot. Rule checks run only after these gates succeed.
func Freshness(s Snapshot, d DocumentBase, current CurrentEvidence, kb coaching.VerifiedKnowledge, now time.Time) (string, []Issue, error) {
	if s.Operation != d.Operation {
		return "invalid", []Issue{staleIssue("V2.operation_mismatch", "operation")}, nil
	}
	if s.AsOf != current.Today || s.GeneratedAt.After(now) || now.Sub(s.GeneratedAt) > 24*time.Hour {
		return "invalid", []Issue{staleIssue("V2.snapshot_expired", "snapshot_id")}, nil
	}
	issues := []Issue{}
	if d.CalendarVersion != current.Head {
		issues = append(issues, staleIssue("V3.stale_base", "base_calendar_version"))
	}
	if (d.BlockVersion == nil) != (current.BlockID == nil) || (d.BlockVersion != nil && *d.BlockVersion != *current.BlockID) {
		issues = append(issues, staleIssue("V3.stale_base", "base_block_version_id"))
	}
	if len(issues) > 0 {
		return "stale", issues, nil
	}
	_, hash, err := coaching.Fingerprint(current.Sources, kb)
	if err != nil {
		return "", nil, err
	}
	if hash != s.Fingerprint || s.KBDigest != kb.Digest {
		return "stale", []Issue{staleIssue("V3.stale_sources", "snapshot_id")}, nil
	}
	return "pending", issues, nil
}
