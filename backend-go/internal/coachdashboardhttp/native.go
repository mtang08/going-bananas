package coachdashboardhttp

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drilldowns"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/protocol"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshots"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
)

// NewNative starts the local dashboard with its six transactional coaching tools.
func NewNative(ctx context.Context, pool *pgxpool.Pool, cfg LocalConfig) (*Local, error) {
	if cfg.Mode != "demo" && cfg.Mode != "test" && cfg.Mode != "real" {
		return nil, errors.New("unknown native coaching dashboard mode")
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	n := nativeTools{now: now, kbRoot: filepath.Join(cfg.RepoRoot, "running_coach_kb")}
	return NewLocal(ctx, pool, cfg, coachdashboard.ToolHandlers{
		Active: n.active, Snapshot: n.snapshot, Findings: n.findings, Query: drilldowns.Reader{Now: now}.Query, SavePending: n.save,
		Schema: func(context.Context, pgx.Tx) (coachdashboard.Object, error) {
			var shape coachdashboard.Object
			err := json.Unmarshal(protocol.Proposal(), &shape)
			return shape, err
		},
		// The per-turn coach instructions interpret agreement in the conversation.
		// The dispatcher fences this callback to the authenticated current user turn.
		AuthorizePending: func(_ context.Context, _ pgx.Tx, msg coachdashboard.Message) (bool, error) {
			return msg.Role == "user" && msg.ClientMessageID != nil && strings.TrimSpace(msg.Text) != "", nil
		},
	})
}

type nativeTools struct {
	now    func() time.Time
	kbRoot string
}

func (n nativeTools) snapshot(ctx context.Context, tx pgx.Tx, operation string) (coachdashboard.Object, error) {
	now := n.now().UTC()
	zone, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	location, err := time.LoadLocation(zone)
	if err != nil {
		return nil, err
	}
	packet, err := snapshots.Build(ctx, tx, operation, now.In(location).Format(time.DateOnly), now, n.kbRoot)
	if errors.Is(err, snapshots.ErrKnowledgeUnavailable) {
		return nil, &coachdashboard.ToolFailure{Code: "knowledge_unavailable", Message: "Verified research is unavailable in this workspace."}
	}
	return packet, err
}

func (n nativeTools) findings(ctx context.Context, tx pgx.Tx, include string) (coachdashboard.Object, error) {
	now := n.now().UTC()
	if _, err := exceptions.Detect(ctx, tx, now); err != nil {
		return nil, err
	}
	return exceptions.View(ctx, tx, now, include)
}

func (n nativeTools) active(ctx context.Context, tx pgx.Tx) (*coachdashboard.ActiveDraft, error) {
	d, err := drafts.InTransaction(tx).ActiveProposal(ctx, n.now().UTC(), n.kbRoot)
	if err != nil || d == nil {
		return nil, err
	}
	var header struct{ Operation string }
	if err := json.Unmarshal(d.Document, &header); err != nil {
		return nil, err
	}
	return &coachdashboard.ActiveDraft{ID: d.ProposalID, SnapshotID: d.SnapshotID, Operation: header.Operation, Revision: d.Revision, View: coachdashboard.Object{"proposal": d.Proposal, "proposal_id": d.ProposalID.String(), "revision": d.Revision, "status": d.Status, "is_current": d.IsCurrent, "document": d.Document}}, nil
}

func toolIssues(issues []drafts.Issue) []coachdashboard.Object {
	out := make([]coachdashboard.Object, 0, len(issues))
	for _, issue := range issues {
		out = append(out, coachdashboard.Object{"code": issue.Code, "path": issue.Path, "message": issue.Message})
	}
	return out
}

func (n nativeTools) save(ctx context.Context, tx pgx.Tx, req coachdashboard.PendingRequest) (coachdashboard.PendingResult, error) {
	raw, err := json.Marshal(req.Document)
	if err != nil {
		return coachdashboard.PendingResult{}, err
	}
	store := drafts.InTransaction(tx)
	now := n.now().UTC()
	validate := drafts.NewValidator(n.kbRoot)
	var result drafts.EditResult
	if req.ProposalID == uuid.Nil {
		result, err = store.Submit(ctx, raw, now, validate)
	} else {
		result, err = store.Revise(ctx, req.ProposalID, drafts.RevisionRequest{ExpectedRevision: req.ExpectedRevision, Reason: req.Reason, Document: raw}, now, validate)
	}
	var domain *drafts.Error
	if errors.As(err, &domain) {
		failure := &coachdashboard.ToolFailure{Code: domain.Code, Message: domain.Message}
		var command *drafts.CommandError
		if errors.As(err, &command) {
			failure.Issues = toolIssues(command.Issues)
		}
		return coachdashboard.PendingResult{}, failure
	}
	return coachdashboard.PendingResult{ID: result.ID, Revision: result.Revision, Status: result.Status, Issues: toolIssues(result.Issues)}, err
}
