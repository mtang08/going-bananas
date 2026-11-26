package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"time"
)

type View struct {
	Data     any
	Revision int
}

func (s Store) DataRevision(ctx context.Context) (int, error) {
	var revision int
	err := s.withTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
	})
	return revision, err
}
func (s Store) ReadProposal(ctx context.Context, id uuid.UUID, which string, revision int, now time.Time, kbRoot string) (View, error) {
	var view View
	err := s.withTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		var head int
		if err := tx.QueryRow(ctx, "SELECT data_revision,calendar_head_version FROM app_state WHERE id=1").Scan(&view.Revision, &head); err != nil {
			return err
		}
		if which == "revision" {
			var data json.RawMessage
			err := tx.QueryRow(ctx, `SELECT jsonb_build_object('proposal_id',proposal_id,'revision',revision,'saved_at',saved_at,'reason',reason,'document',payload) FROM coach_proposal_revisions WHERE proposal_id=$1 AND revision=$2`, id, revision).Scan(&data)
			if errors.Is(err, pgx.ErrNoRows) {
				return &Error{"proposal_revision_not_found", "Proposal revision not found", 404}
			}
			if err != nil {
				return err
			}
			view.Data, err = timedRow(data, "saved_at")
			return err
		}
		var d Draft
		if err := loadDraft(ctx, tx, id, &d); err != nil {
			return err
		}
		current := false
		snap, err := LoadSnapshot(ctx, tx, d.SnapshotID)
		if err != nil {
			return err
		}
		if d.Status == "pending" {
			current, err = isCurrent(ctx, tx, d.Payload, snap, now, kbRoot)
			if err != nil {
				return err
			}
		}
		if which == "document" {
			view.Data = map[string]any{"proposal_id": id, "revision": d.Revision, "status": d.Status, "is_current": current, "document": d.Payload}
			return nil
		}
		var detail map[string]json.RawMessage
		var evidenceIDs, policyIDs []string
		err = tx.QueryRow(ctx, `SELECT to_jsonb(p)-ARRAY['payload','decision_idempotency_key','decision_hash','input_hash'],evidence_ids,policy_ids FROM coach_proposals p WHERE p.id=$1`, id).Scan(&detail, &evidenceIDs, &policyIDs)
		if err != nil {
			return err
		}
		if err := viewTimes(detail, "submitted_at", "decided_at", "discarded_at"); err != nil {
			return err
		}
		output := map[string]any{}
		for k, v := range detail {
			output[k] = v
		}
		sources, err := coaching.CitedSources(kbRoot, evidenceIDs, policyIDs)
		if err != nil {
			sources = []coaching.Citation{}
		}
		output["head"], output["is_current"], output["sources"] = head, current, sources
		var revs, changes, anchors, patch, interruption json.RawMessage
		err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(jsonb_build_object('revision',revision,'saved_at',saved_at,'reason',reason,'changed_change_ids',changed_change_ids,'changed_fields',changed_fields) ORDER BY revision DESC),'[]'::jsonb) FROM coach_proposal_revisions WHERE proposal_id=$1`, id).Scan(&revs)
		if err != nil {
			return err
		}
		var doc map[string]json.RawMessage
		if err := json.Unmarshal(d.Payload, &doc); err != nil {
			return err
		}
		output["revisions"], err = timedRows(revs, "saved_at")
		if err != nil {
			return err
		}
		output["exception"] = doc["exception"]
		output["event_review"] = doc["event_review"]
		output["patch_resolutions"] = json.RawMessage("[]")
		if raw, ok := doc["patch_resolutions"]; ok {
			output["patch_resolutions"] = raw
		}
		if has(detail["decision_result"]) {
			var m map[string]any
			if err := json.Unmarshal(detail["decision_result"], &m); err != nil {
				return err
			}
			m["proposal_id"] = id
			output["decision_result"] = m
		}
		err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(a || jsonb_build_object('anchor_key',(a->>'kind')||'-'||(((a->>'calibrated_at')::timestamptz AT TIME ZONE coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date)::text) ORDER BY n),'[]'::jsonb)
 FROM coach_proposals p CROSS JOIN LATERAL jsonb_array_elements(coalesce(p.anchor_changes,'[]')) WITH ORDINALITY items(a,n) WHERE p.id=$1`, id).Scan(&anchors)
		if err != nil {
			return err
		}
		output["anchor_changes"] = anchors
		err = tx.QueryRow(ctx, `SELECT coalesce(jsonb_agg(jsonb_build_object('change_id',c.change_id,'op',c.op,'session_uid',c.session_uid,'before',c.before,'after',c.after,'reason',c.reason,'decision',c.decision,'material_flags',coalesce(flags.item->'material_flags','[]'::jsonb),'current',CASE WHEN h.deleted IS false THEN to_jsonb(h)-ARRAY['id','revision','session_uid','calendar_version_number','deleted','certainty','legacy_payload','legacy_unstructured','notes'] END) ORDER BY substr(c.change_id,2)::bigint),'[]'::jsonb)
 FROM coach_proposal_changes c LEFT JOIN LATERAL (SELECT * FROM calendar_session_revisions WHERE session_uid=c.session_uid AND calendar_version_number<=$2 ORDER BY calendar_version_number DESC,revision DESC LIMIT 1) h ON true LEFT JOIN LATERAL (SELECT item FROM jsonb_array_elements($3::jsonb->'changes') item WHERE item->>'change_id'=c.change_id) flags ON true WHERE c.proposal_id=$1`, id, head, d.Payload).Scan(&changes)
		if err != nil {
			return err
		}
		output["changes"] = changes
		err = tx.QueryRow(ctx, `SELECT (SELECT to_jsonb(e) FROM exception_patches e WHERE proposal_id=$1),CASE WHEN jsonb_typeof(s.payload#>'{running_interruption,interruption}')='object' THEN
 jsonb_build_object('today',s.payload#>'{running_interruption,today}','interruption',s.payload#>'{running_interruption,interruption}','affected_runs',s.payload#>'{running_interruption,affected_runs}','affected_runs_omitted',s.payload#>'{running_interruption,affected_runs_omitted}') END FROM coach_snapshots s WHERE id=$2`, id, snap.ID).Scan(&patch, &interruption)
		if err != nil {
			return err
		}
		output["patch"], err = timedRow(patch, "created_at", "resolved_at")
		output["running_interruption"] = interruption
		view.Data = output
		return err
	})
	return view, err
}

// ActiveDraft carries the stable IDs and exact reusable authored document from
// the active-proposal dashboard tool's locked read.
type ActiveDraft struct {
	ProposalID uuid.UUID       `json:"proposal_id"`
	SnapshotID uuid.UUID       `json:"-"`
	Revision   int             `json:"revision"`
	Status     string          `json:"status"`
	IsCurrent  bool            `json:"is_current"`
	Document   json.RawMessage `json:"document"`
	Proposal   json.RawMessage `json:"proposal"`
}

func (s Store) ActiveProposal(ctx context.Context, now time.Time, kbRoot string) (*ActiveDraft, error) {
	var out ActiveDraft
	err := s.withTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := LockPlanning(ctx, tx); err != nil {
			return err
		}
		err := tx.QueryRow(ctx, `SELECT id,snapshot_id,revision,status,payload,jsonb_build_object('id',id,'revision',revision,'operation',operation,'status',status,'submitted_at',submitted_at,'decided_at',decided_at,'discarded_at',discarded_at,'headline',headline,'base_calendar_version',base_calendar_version,'change_count',jsonb_array_length(coalesce(payload->'changes','[]'))) FROM coach_proposals WHERE status IN ('pending','stale','invalid') ORDER BY submitted_at DESC,id DESC LIMIT 1`).Scan(&out.ProposalID, &out.SnapshotID, &out.Revision, &out.Status, &out.Document, &out.Proposal)
		if err != nil {
			return err
		}
		out.Proposal, err = timedRow(out.Proposal, "submitted_at", "decided_at", "discarded_at")
		if err != nil {
			return err
		}
		if out.Status != "pending" {
			return nil
		}
		snap, err := LoadSnapshot(ctx, tx, out.SnapshotID)
		if err != nil {
			return err
		}
		out.IsCurrent, err = isCurrent(ctx, tx, out.Document, snap, now, kbRoot)
		return err
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &out, nil
}
func isCurrent(ctx context.Context, tx pgx.Tx, payload json.RawMessage, snap Snapshot, now time.Time, kbRoot string) (bool, error) {
	kb, _, err := coaching.VerifySelection(kbRoot, snap.Selection)
	if err != nil {
		return false, nil
	}
	var base DocumentBase
	if err := json.Unmarshal(payload, &base); err != nil {
		return false, err
	}
	_, facts, err := LoadRuleContext(ctx, tx, snap, now)
	if err != nil {
		return false, err
	}
	status, _, err := Freshness(snap, base, facts, kb, now)
	return status == "pending", err
}
