package coachdashboard

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"slices"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

//go:embed protocol/tools.json
var toolDefinitions []byte

// ActiveDraft includes the public summary and reusable proposal document, alongside
// the authoritative identity returned under the global planning writer lock.
type ActiveDraft struct {
	ID, SnapshotID uuid.UUID
	Revision       int
	Operation      string
	View           Object
}

type PendingRequest struct {
	Document         Object
	ProposalID       uuid.UUID
	ExpectedRevision int
	Reason           string
}

type PendingResult struct {
	ID       uuid.UUID
	Revision int
	Status   string
	Issues   []Object
}

// Handlers participate in the dispatcher's transaction. They must not commit it.
// Snapshot, Active and Findings return the same filtered domain payloads as their
// dashboard counterparts. Query returns the drill-down data before privacy filtering.
type ToolHandlers struct {
	Active           func(context.Context, pgx.Tx) (*ActiveDraft, error)
	Findings         func(context.Context, pgx.Tx, string) (Object, error)
	Snapshot         func(context.Context, pgx.Tx, string) (Object, error)
	Query            func(context.Context, pgx.Tx, Object) (any, error)
	Schema           func(context.Context, pgx.Tx) (Object, error)
	AuthorizePending func(context.Context, pgx.Tx, Message) (bool, error)
	SavePending      func(context.Context, pgx.Tx, PendingRequest) (PendingResult, error)
}

type ToolDispatcher struct {
	store    *Store
	handlers ToolHandlers
}

func NewDashboardTools(store *Store, handlers ToolHandlers) *ToolDispatcher {
	return &ToolDispatcher{store, handlers}
}

func (*ToolDispatcher) Definitions() []ToolDefinition {
	var defs []ToolDefinition
	if err := json.Unmarshal(toolDefinitions, &defs); err != nil {
		panic(err)
	}
	return defs
}

// ToolFailure is safe to expose to the coach. Returning it rolls back domain and review writes.
type ToolFailure struct {
	Code, Message string
	Issues        []Object
}

func (e *ToolFailure) Error() string         { return e.Message }
func toolFailure(code, message string) error { return &ToolFailure{Code: code, Message: message} }
func invalidArgs() error {
	return toolFailure("invalid_tool_arguments", "Check the coaching tool's arguments.")
}
func unavailable() error {
	return toolFailure("tool_unavailable", "This coaching tool is unavailable.")
}
func errorView(e *ToolFailure) Object {
	issues := e.Issues
	if issues == nil {
		issues = []Object{}
	}
	return Object{"error": e.Code, "message": e.Message, "errors": issues}
}

func (d *ToolDispatcher) Call(ctx context.Context, turnID, name string, args Object) (Object, error) {
	if !allowedTool(name) {
		return errorView(&ToolFailure{Code: "unknown_tool", Message: "This app only exposes its listed coaching tools."}), nil
	}
	var result Object
	err := d.store.withReview(ctx, func(tx pgx.Tx, r Review) error {
		if turnID == "" || r.Status != "running" || r.ActiveTurn != turnID {
			return toolFailure("interrupted", "This coaching turn has stopped.")
		}
		var err error
		result, err = d.dispatch(ctx, tx, &r, name, args)
		if err != nil {
			return err
		}
		switch name {
		case "active_proposal", "coaching_snapshot", "save_pending_proposal":
			return d.store.save(ctx, tx, r)
		}
		return nil
	})
	var failure *ToolFailure
	if errors.As(err, &failure) {
		return errorView(failure), nil
	}
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (d *ToolDispatcher) dispatch(ctx context.Context, tx pgx.Tx, r *Review, name string, args Object) (Object, error) {
	h := d.handlers
	switch name {
	case "active_proposal":
		if len(args) != 0 {
			return nil, invalidArgs()
		}
		draft, err := d.active(ctx, tx)
		if err != nil {
			return nil, err
		}
		r.ReadActiveProposal = true
		r.ObservedProposal = ""
		r.ObservedRevision = 0
		if draft == nil {
			return Object{"proposal": nil}, nil
		}
		r.ProposalID = draft.ID.String()
		r.ObservedProposal = r.ProposalID
		r.ProposalRevision = draft.Revision
		r.ObservedRevision = draft.Revision
		rememberSnapshot(r, draft.SnapshotID.String())
		return draft.View, nil
	case "coaching_snapshot":
		op := field(args, "operation")
		if len(args) != 1 || !slices.Contains([]string{"proceed_or_modify_today", "review_rolling_plan", "select_quality_session", "review_training_block", "recalibrate_intensity", "handle_goal_or_race_change", "exception_review", "post_event_review"}, op) {
			return nil, invalidArgs()
		}
		if h.Snapshot == nil {
			return nil, unavailable()
		}
		view, err := h.Snapshot(ctx, tx, op)
		if err != nil {
			return nil, err
		}
		id, err := uuid.Parse(field(view, "snapshot_id"))
		if err != nil {
			return nil, fmt.Errorf("invalid dashboard snapshot identity")
		}
		rememberSnapshot(r, id.String())
		return view, nil
	case "review_findings":
		include := "active"
		if len(args) != 0 {
			include = field(args, "include")
			if len(args) != 1 || (include != "active" && include != "recent") {
				return nil, invalidArgs()
			}
		}
		if h.Findings == nil {
			return nil, unavailable()
		}
		data, err := h.Findings(ctx, tx, include)
		if err != nil {
			return nil, err
		}
		return filteredObject(data)
	case "coaching_query":
		if err := validateQuery(args); err != nil {
			return nil, err
		}
		if h.Query == nil {
			return nil, unavailable()
		}
		data, err := h.Query(ctx, tx, args)
		if err != nil {
			return nil, err
		}
		return filteredObject(Object{"query": args["name"], "data": data})
	case "proposal_schema":
		if len(args) != 0 {
			return nil, invalidArgs()
		}
		if h.Schema == nil {
			return nil, unavailable()
		}
		schema, err := h.Schema(ctx, tx)
		if err != nil {
			return nil, err
		}
		return Object{"protocol": "coach_proposal.v2", "activation": "manual", "required_authority": "calendar", "proposal": schema}, nil
	default:
		req, err := pendingArgs(args)
		if err != nil {
			return nil, err
		}
		return d.savePending(ctx, tx, r, req)
	}
}

func (d *ToolDispatcher) active(ctx context.Context, tx pgx.Tx) (*ActiveDraft, error) {
	if d.handlers.Active == nil {
		return nil, unavailable()
	}
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(71382413)"); err != nil {
		return nil, err
	}
	draft, err := d.handlers.Active(ctx, tx)
	if err == nil && draft != nil && (draft.ID == uuid.Nil || draft.SnapshotID == uuid.Nil || draft.Revision < 1 || draft.View == nil) {
		return nil, errors.New("incomplete active dashboard draft")
	}
	return draft, err
}

func rememberSnapshot(r *Review, id string) {
	if !slices.Contains(r.SnapshotIDs, id) {
		r.SnapshotIDs = append(r.SnapshotIDs, id)
	}
}

func (d *ToolDispatcher) savePending(ctx context.Context, tx pgx.Tx, r *Review, req PendingRequest) (Object, error) {
	if !r.ReadActiveProposal {
		return nil, toolFailure("active_proposal_required", "Read the current draft before saving a proposal.")
	}
	id, err := uuid.Parse(field(req.Document, "snapshot_id"))
	if err != nil || !slices.Contains(r.SnapshotIDs, id.String()) {
		return nil, toolFailure("snapshot_required", "Use the snapshot ID returned in this review.")
	}
	h := d.handlers
	if len(r.Messages) == 0 {
		return nil, toolFailure("interrupted", "This coaching turn has stopped.")
	}
	msg := r.Messages[len(r.Messages)-1]
	permitted := false
	if h.AuthorizePending != nil && msg.Role == "user" && msg.ID == r.ActiveTurn && msg.ClientMessageID != nil {
		permitted, err = h.AuthorizePending(ctx, tx, msg)
		if err != nil {
			return nil, err
		}
	}
	if !permitted {
		return nil, toolFailure("athlete_agreement_required", "Save a pending draft after the athlete agrees or asks to publish.")
	}
	draft, err := d.active(ctx, tx)
	if err != nil {
		return nil, err
	}
	if draft == nil && (req.ProposalID != uuid.Nil || r.ObservedProposal != "") {
		return nil, toolFailure("proposal_decided", "The open draft was decided. Do not recreate it as a retry.")
	}
	if draft != nil {
		if req.ProposalID != draft.ID || r.ObservedProposal != draft.ID.String() || (field(req.Document, "operation") == "exception_review" && draft.Operation != "exception_review") {
			return nil, toolFailure("active_proposal_exists", "Read the current draft and revise its stable ID.")
		}
		if draft.Revision != req.ExpectedRevision || r.ObservedRevision != draft.Revision {
			return nil, toolFailure("proposal_revision_conflict", "This proposal was revised. Read the latest draft before editing.")
		}
	}
	if h.SavePending == nil {
		return nil, unavailable()
	}
	result, err := h.SavePending(ctx, tx, req)
	if err != nil {
		return nil, err
	}
	if result.Status != "pending" {
		code := "invalid_proposal"
		if result.Status == "stale" {
			code = "stale_evidence"
		}
		return nil, &ToolFailure{code, "The draft did not pass current validation.", result.Issues}
	}
	if result.ID == uuid.Nil || result.Revision < 1 || (draft != nil && (result.ID != draft.ID || result.Revision != draft.Revision+1)) {
		return nil, errors.New("invalid pending proposal identity")
	}
	r.ProposalID = result.ID.String()
	r.ProposalRevision = result.Revision
	r.ObservedProposal = r.ProposalID
	r.ObservedRevision = result.Revision
	return Object{"proposal_id": r.ProposalID, "revision": result.Revision, "status": "pending", "review_path": "/#proposal/" + r.ProposalID}, nil
}
