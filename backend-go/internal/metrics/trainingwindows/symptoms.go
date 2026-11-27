package trainingwindows

import (
	"context"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
)

var symptomConfig = object{"link_hours": 48, "link_rule": "activity_id_else_associations.preceding_sessions_first", "recurrence_lookback_days": 28, "bucket_0_24": []string{"during", "immediately_after", "next_morning"}, "bucket_24_48": []string{"hours_24_48"}, "bucket_later": []string{"later"}, "unknown_timing_rule": "by_hours_after_end", "site_normalization": "strip_lower", "gait_order": []string{"yes", "unsure", "no", "unknown"}}

func dayStart(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location())
}

type siteKey struct{ site, side string }
type siteStats struct {
	count       int
	days        map[string]bool
	max, latest float64
	timing      string
	gait        bool
}

func RefreshSymptoms(ctx context.Context, tx pgx.Tx, asOf, now time.Time) error {
	return calculateSymptoms(ctx, tx, asOf, func(r metrics.Result) error { _, err := metrics.StoreResult(ctx, tx, r, now); return err })
}

func calculateSymptoms(ctx context.Context, tx pgx.Tx, asOf time.Time, emit func(metrics.Result) error) error {
	start, end := dayStart(asOf).AddDate(0, 0, -27), dayStart(asOf).AddDate(0, 0, 1)
	rows, err := tx.Query(ctx, `SELECT c.id,c.version,c.activity_id,c.kind,c.gait_change,
 to_char(c.observed_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM c.observed_at)::integer%1000000<>0 THEN to_char(c.observed_at,'.US') ELSE '' END||to_char(c.observed_at,'TZH:TZM'),
 (c.observed_at AT TIME ZONE $3)::date::text,r.id,r.site,r.side,r.severity::float8,r.timing
 FROM checkins_v2 c LEFT JOIN symptom_reports r ON r.checkin_id=c.id
 WHERE c.observed_at >= $1 AND c.observed_at < $2 ORDER BY c.observed_at,c.id,r.id`, start, end, asOf.Location().String())
	if err != nil {
		return err
	}
	defer rows.Close()
	ids := []uuid.UUID{}
	checkins := []object{}
	groups := map[siteKey]*siteStats{}
	for rows.Next() {
		var id uuid.UUID
		var activity, report *uuid.UUID
		var version int
		var kind, observed, day string
		var gait, site, side, timing *string
		var severity *float64
		if err := rows.Scan(&id, &version, &activity, &kind, &gait, &observed, &day, &report, &site, &side, &severity, &timing); err != nil {
			return err
		}
		if len(ids) == 0 || ids[len(ids)-1] != id {
			ids = append(ids, id)
			checkins = append(checkins, object{"id": id, "version": version, "activity_id": activity, "kind": kind, "gait_change": gait, "observed_at": observed, "reports": []object{}})
		}
		if report == nil {
			continue
		}
		ref := checkins[len(checkins)-1]
		ref["reports"] = append(ref["reports"].([]object), object{"id": report, "site": site, "side": side, "severity": severity, "timing": timing})
		key := siteKey{strings.ToLower(strings.TrimSpace(*site)), *side}
		g := groups[key]
		if g == nil {
			g = &siteStats{days: map[string]bool{}}
			groups[key] = g
		}
		g.count++
		g.max = max(g.max, *severity)
		g.latest = *severity
		g.timing = *timing
		g.gait = g.gait || (gait != nil && *gait == "yes")
		if *severity > 0 {
			g.days[day] = true
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	hash, err := metrics.Digest(checkins)
	if err != nil {
		return err
	}
	refs := object{"checkin_ids": ids, "checkins": checkins, "input_hash": hash}
	keys := make([]siteKey, 0, len(groups))
	for k := range groups {
		keys = append(keys, k)
	}
	slices.SortFunc(keys, func(a, b siteKey) int {
		if a.site == b.site {
			return strings.Compare(a.side, b.side)
		}
		return strings.Compare(a.site, b.site)
	})
	sites := []object{}
	for _, k := range keys {
		g := groups[k]
		sites = append(sites, object{"site": k.site, "side": k.side, "report_count": g.count, "recurrence_days": len(g.days), "max_severity": g.max, "latest_severity": g.latest, "latest_timing": g.timing, "gait_change_reported": g.gait})
	}
	key := "w28:" + asOf.Format(time.DateOnly)
	r := metrics.Result{MetricID: "symptom_response_timeline", MethodVersion: "v1", SubjectType: "window", SubjectKey: key, WindowLabel: key, WindowStart: &start, WindowEnd: &end, Config: symptomConfig, SourceRefs: refs, Timezone: asOf.Location().String(), Status: "available", Value: object{"checkin_count": len(ids), "sites": sites}}
	if len(ids) == 0 {
		r.Status = "missing"
		r.Value = nil
		r.ReasonCodes = []string{"NO_CHECKINS_IN_WINDOW"}
	}
	err = emit(r)
	return err
}
