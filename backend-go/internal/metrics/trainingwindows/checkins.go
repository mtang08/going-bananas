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

type report struct {
	id                 uuid.UUID
	site, side, timing string
	severity           float64
}
type checkin struct {
	id          uuid.UUID
	version     int
	activity    *uuid.UUID
	kind, stamp string
	observed    time.Time
	gait        *string
	reports     []report
}

func linkedCheckins(ctx context.Context, tx pgx.Tx, id uuid.UUID, zone string) ([]checkin, error) {
	rows, err := tx.Query(ctx, `SELECT c.id,c.version,c.activity_id,c.kind,c.observed_at,c.gait_change,
 to_char(c.observed_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM c.observed_at)::integer%1000000<>0 THEN to_char(c.observed_at,'.US') ELSE '' END||to_char(c.observed_at,'TZH:TZM'),
 r.id,r.site,r.side,r.severity::float8,r.timing FROM checkins_v2 c LEFT JOIN symptom_reports r ON r.checkin_id=c.id
 WHERE c.activity_id=$1 OR(c.activity_id IS NULL AND NOT starts_with(c.idempotency_key,'phone-first-steps:') AND $1=(SELECT a.id FROM activities a LEFT JOIN LATERAL(SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) an ON true
 WHERE a.sport IN('running','trail_running','treadmill_running') AND a.resolution_state='resolved' AND NOT coalesce(an.excluded,false)
 AND a.end_at BETWEEN c.observed_at-interval '48 hours' AND c.observed_at AND (a.start_at AT TIME ZONE $2)::date BETWEEN (c.observed_at AT TIME ZONE $2)::date-3 AND (c.observed_at AT TIME ZONE $2)::date
 ORDER BY a.end_at DESC,a.id LIMIT 1)) ORDER BY c.observed_at,c.id,r.id`, id, zone)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []checkin{}
	for rows.Next() {
		var c checkin
		var rid *uuid.UUID
		var site, side, timing *string
		var sev *float64
		if err := rows.Scan(&c.id, &c.version, &c.activity, &c.kind, &c.observed, &c.gait, &c.stamp, &rid, &site, &side, &sev, &timing); err != nil {
			return nil, err
		}
		if len(out) == 0 || out[len(out)-1].id != c.id {
			out = append(out, c)
		}
		if rid != nil {
			c := &out[len(out)-1]
			c.reports = append(c.reports, report{*rid, *site, *side, *timing, *sev})
		}
	}
	return out, rows.Err()
}

func checkinRefs(facts []checkin, gait bool) ([]string, []object) {
	ids, refs := []string{}, []object{}
	for _, c := range facts {
		ids = append(ids, c.id.String())
		reports := []object{}
		for _, r := range c.reports {
			reports = append(reports, object{"id": r.id, "site": r.site, "side": r.side, "severity": r.severity, "timing": r.timing})
		}
		ref := object{"id": c.id, "version": c.version, "activity_id": c.activity, "observed_at": c.stamp, "kind": c.kind, "reports": reports}
		if gait {
			ref["gait_change"] = c.gait
		}
		refs = append(refs, ref)
	}
	return ids, refs
}
func runRefs(r *metrics.Run) object {
	return object{"activity": object{"id": r.ID, "source_revision": r.SourceRevision, "source_refs": r.Refs}, "fit": r.FIT, "plan": nil, "completion_association_hash": nil, "activity_ids": []uuid.UUID{r.ID}}
}

func bucket(timing string, hours *float64) string {
	switch timing {
	case "during", "immediately_after", "next_morning":
		return "0_24"
	case "hours_24_48":
		return "24_48"
	case "later":
		return "later"
	}
	if hours == nil {
		return "unknown"
	}
	if *hours < 24 {
		return "0_24"
	}
	if *hours <= 48 {
		return "24_48"
	}
	return "later"
}
func recordMax(site object, key string, value float64) {
	prior, ok := site[key].(float64)
	if !ok || value > prior {
		site[key] = value
	}
}

func symptomActivity(ctx context.Context, tx pgx.Tx, r *metrics.Run, facts []checkin, zone string) (*metrics.Result, error) {
	refs := runRefs(r)
	out := metrics.Result{MetricID: "symptom_response_timeline", MethodVersion: "v1", SubjectType: "activity", SubjectKey: r.ID.String(), WindowStart: &r.Start, WindowEnd: r.End, Config: symptomConfig, SourceRefs: refs, Timezone: zone}
	if !r.Eligible {
		out.Status = "not_applicable"
		out.ReasonCodes = []string{"ACTIVITY_EXCLUDED"}
		return &out, nil
	}
	ids, rows := checkinRefs(facts, true)
	hash, err := metrics.Digest(rows)
	if err != nil {
		return nil, err
	}
	refs["checkin_ids"], refs["checkins"], refs["input_hash"] = ids, rows, hash
	if r.End == nil {
		out.QualityFlags = []string{"END_TIME_UNKNOWN"}
	}
	if len(facts) == 0 {
		out.Status = "missing"
		out.ReasonCodes = []string{"NO_LINKED_CHECKIN"}
		return &out, nil
	}
	var endStamp *string
	err = tx.QueryRow(ctx, `SELECT to_char(end_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM end_at)::integer%1000000<>0 THEN to_char(end_at,'.US') ELSE '' END||to_char(end_at,'TZH:TZM') FROM activities WHERE id=$1`, r.ID).Scan(&endStamp)
	if err != nil {
		return nil, err
	}
	delayed := false
	gaits := map[string]bool{}
	reports := []object{}
	sites := map[siteKey]object{}
	for _, c := range facts {
		if c.gait != nil {
			gaits[*c.gait] = true
		}
		delayed = delayed || c.kind == "delayed_followup"
		var hrs, rounded *float64
		if r.End != nil {
			v := c.observed.Sub(*r.End).Hours()
			hrs = &v
			h := round(v, 1)
			rounded = &h
		}
		for _, report := range c.reports {
			reports = append(reports, object{"checkin_id": c.id, "observed_at": c.stamp, "kind": c.kind, "site": report.site, "side": report.side, "severity": report.severity, "timing": report.timing, "gait_change": c.gait, "hours_after_end": rounded})
			key := siteKey{strings.ToLower(strings.TrimSpace(report.site)), report.side}
			site := sites[key]
			if site == nil {
				site = object{"site": key.site, "side": key.side, "max_severity_0_24h": nil, "max_severity_24_48h": nil, "first_report_hours_after_end": rounded}
				sites[key] = site
			}
			site["latest_severity"], site["latest_observed_at"] = report.severity, c.stamp
			switch bucket(report.timing, hrs) {
			case "0_24":
				recordMax(site, "max_severity_0_24h", report.severity)
			case "24_48":
				recordMax(site, "max_severity_24_48h", report.severity)
			}
		}
	}
	if !delayed {
		out.QualityFlags = append(out.QualityFlags, "DELAYED_FOLLOWUP_MISSING")
	}
	gait := "unknown"
	for _, g := range []string{"yes", "unsure", "no"} {
		if gaits[g] {
			gait = g
			break
		}
	}
	keys := make([]siteKey, 0, len(sites))
	for k := range sites {
		keys = append(keys, k)
	}
	slices.SortFunc(keys, func(a, b siteKey) int {
		if a.site == b.site {
			return strings.Compare(a.side, b.side)
		}
		return strings.Compare(a.site, b.site)
	})
	ordered := []object{}
	for _, k := range keys {
		ordered = append(ordered, sites[k])
	}
	out.Status = "available"
	out.QualityStatus = "good"
	if len(out.QualityFlags) > 0 {
		out.QualityStatus = "limited"
	}
	out.Value = object{"activity_end_at": endStamp, "delayed_followup_answered": delayed, "reports": reports, "sites": ordered, "gait_change": gait}
	return &out, nil
}
