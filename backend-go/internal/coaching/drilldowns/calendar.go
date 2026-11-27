package drilldowns

import (
	"context"

	"github.com/jackc/pgx/v5"
)

const rowView = "to_jsonb(r) || jsonb_build_object('is_original',revision=1,'changed_by_version',calendar_version_number)"

// CalendarDiff reads both versions under the shared planning lock.
func CalendarDiff(ctx context.Context, tx pgx.Tx, from, to int) (object, error) {
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(71382413)"); err != nil {
		return nil, err
	}
	var valid bool
	if err := tx.QueryRow(ctx, `SELECT NOT EXISTS (SELECT FROM unnest($1::int[]) v WHERE v<0 OR v>coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0)
		OR (v<>0 AND NOT EXISTS(SELECT FROM calendar_versions WHERE number=v)))`, []int{from, to}).Scan(&valid); err != nil {
		return nil, err
	}
	if !valid {
		return nil, failure("calendar_version_not_found", "Calendar version not found")
	}
	rows, err := wireRows(ctx, tx, `WITH l AS (SELECT DISTINCT ON(session_uid) session_uid,`+rowView+` AS row,deleted
		FROM calendar_session_revisions r WHERE calendar_version_number <= $1 AND $1>0 ORDER BY session_uid,calendar_version_number DESC,revision DESC),
		r AS (SELECT DISTINCT ON(session_uid) session_uid,`+rowView+` AS row,deleted
		FROM calendar_session_revisions r WHERE calendar_version_number <= $2 AND $2>0 ORDER BY session_uid,calendar_version_number DESC,revision DESC),
		pairs AS (SELECT session_uid,CASE WHEN NOT l.deleted THEN l.row END AS before,CASE WHEN NOT r.deleted THEN r.row END AS after
		FROM l FULL JOIN r USING(session_uid))
		SELECT jsonb_build_object('session_uid',session_uid,'op',CASE WHEN before IS NULL THEN 'add' WHEN after IS NULL THEN 'delete'
		WHEN before->'local_date' <> after->'local_date' THEN 'move' ELSE 'modify' END,'before',before,'after',after)
		FROM pairs WHERE (before-ARRAY['id','session_uid','revision','calendar_version_number','deleted','certainty','is_original','changed_by_version'])
		IS DISTINCT FROM (after-ARRAY['id','session_uid','revision','calendar_version_number','deleted','certainty','is_original','changed_by_version']) ORDER BY session_uid`, from, to)
	return object{"changes": rows}, err
}
