package replay

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"errors"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/garmin/zipinput"
)

var (
	sleepMember  = regexp.MustCompile(`(?:^|/)(?:[0-9]{4}-[0-9]{2}-[0-9]{2}_){2}([0-9]+)_sleepData\.json$`)
	healthMember = regexp.MustCompile(`(?:^|/)(?:[0-9]{4}-[0-9]{2}-[0-9]{2}_){2}([0-9]+)_healthStatusData\.json$`)
	udsMember    = regexp.MustCompile(`(?:^|/)UDSFile_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}-[0-9]{2}-[0-9]{2}\.json$`)
)

type recoveryExport struct {
	rows    map[string][]ActivityRecord
	members map[string]*zip.File
	skipped map[string]int
}

func archiveGMT(v any) (time.Time, bool) {
	s, _ := v.(string)
	t, _, ok := parseISO(strings.ReplaceAll(s, "Z", "+00:00"))
	return t.UTC().Truncate(time.Microsecond), ok
}

func exportObservation(dataset, owner string, row map[string]any) (string, string, float64, int) {
	other := 0
	switch dataset {
	case "sleep":
		start, s := archiveGMT(row["sleepStartTimestampGMT"])
		end, e := archiveGMT(row["sleepEndTimestampGMT"])
		awake, err := nonnegative(row["awakeSleepSeconds"], "invalid")
		value := float64(end.Unix()-start.Unix()) + float64(end.Nanosecond()-start.Nanosecond())/1e9 - awake
		if !s || !e || err != nil || value <= 0 {
			return owner, "sleep_incomplete_or_invalid", 0, 0
		}
		return owner, "", value, 0
	case "resting_hr":
		id, ok := stringID(row["userProfilePK"])
		if !ok {
			return "", "uds_missing_owner_or_date", 0, 0
		}
		n, err := nonnegative(row["restingHeartRate"], "invalid")
		if err != nil || n == 0 {
			return id, "uds_missing_or_invalid_resting_hr", 0, 0
		}
		return id, "", n, 0
	default:
		metrics, _ := row["metrics"].([]any)
		var val any
		matches := 0
		for _, m := range metrics {
			obj, _ := m.(map[string]any)
			if obj["type"] == "HRV" {
				matches++
				val = obj["value"]
			}
		}
		n, err := nonnegative(val, "invalid")
		if matches != 1 || err != nil || n == 0 {
			return owner, "health_status_missing_or_invalid_hrv", 0, 0
		}
		other = len(metrics) - 1
		return owner, "", n, other
	}
}

func scanExportRecovery(reader *zipinput.Reader, archiveHash, activityOwner string) (recoveryExport, error) {
	out := recoveryExport{map[string][]ActivityRecord{}, map[string]*zip.File{}, map[string]int{}}
	byName := map[string]*zip.File{}
	names := []string{}
	for _, f := range reader.File {
		name, err := zipinput.Name(f)
		if err != nil {
			return out, errors.New("invalid_export_archive")
		}
		byName[name] = f
		names = append(names, name)
	}
	slices.Sort(names)
	for _, name := range names {
		var dataset, owner, prefix, field, badDate string
		switch {
		case sleepMember.MatchString(name):
			dataset, owner, prefix, field, badDate = "sleep", sleepMember.FindStringSubmatch(name)[1], "sleep", "sleepEndTimestampGMT-sleepStartTimestampGMT-awakeSleepSeconds", "sleep_incomplete_or_invalid"
		case udsMember.MatchString(name):
			dataset, prefix, field, badDate = "resting_hr", "uds", "restingHeartRate", "uds_missing_owner_or_date"
		case healthMember.MatchString(name):
			dataset, owner, prefix, field, badDate = "hrv", healthMember.FindStringSubmatch(name)[1], "health_status", "metrics[type=HRV].value", "health_status_missing_or_invalid_hrv"
		default:
			continue
		}
		f := byName[name]
		var buf bytes.Buffer
		if err := readExportMember(reader, f, &buf, "invalid_export_archive"); err != nil {
			return out, err
		}
		if !json.Valid(buf.Bytes()) {
			return out, errors.New("invalid_recovery_json")
		}
		dec := json.NewDecoder(&buf)
		dec.UseNumber()
		memberHash := digest(buf.Bytes())
		var data any
		if dec.Decode(&data) != nil {
			return out, errors.New("invalid_recovery_json")
		}
		rows, ok := data.([]any)
		if !ok {
			return out, errors.New("invalid_recovery_array")
		}
		for _, v := range rows {
			row, ok := v.(map[string]any)
			if !ok {
				out.skipped[prefix+"_invalid_row"]++
				continue
			}
			day, ok := recoveryDay(row["calendarDate"])
			if !ok {
				out.skipped[badDate]++
				continue
			}
			id, skip, value, other := exportObservation(dataset, owner, row)
			if skip != "" {
				out.skipped[skip]++
				continue
			}
			if id != activityOwner {
				return out, errors.New("mixed_source_account")
			}
			if dataset == "hrv" {
				out.skipped["health_status_other_metrics_unsupported"] += other
			}
			def := recoveryMetrics[dataset]
			d := day.Format(time.DateOnly)
			out.members[name] = f
			out.rows[dataset] = append(out.rows[dataset], ActivityRecord{
				Record: map[string]any{"userProfilePK": json.Number(id), "calendarDate": d, def.field: value}, Original: row,
				Metadata: map[string]any{"archive_sha256": archiveHash, "member_sha256": memberHash, "source_field": field, "source_record_identity": dataset + ":" + d + ":" + def.statistic},
			})
		}
	}
	return out, nil
}
