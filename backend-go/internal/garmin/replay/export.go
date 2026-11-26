package replay

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"math"
	"path"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/zipinput"
)

type ExportScan struct {
	Records           []ActivityRecord
	Owner, MemberName string
	MemberBytes       []byte
	MemberCount       int
	ExpandedBytes     uint64
}

func exportInventory(reader *zipinput.Reader) (*zip.File, ExportScan, error) {
	var scan ExportScan
	if len(reader.File) > 10_000 {
		return nil, scan, errors.New("archive_too_many_entries")
	}
	names := map[string]bool{}
	var members []*zip.File
	for _, f := range reader.File {
		name, err := zipinput.Name(f)
		if err != nil {
			return nil, scan, errors.New("invalid_export_archive")
		}
		if strings.ContainsAny(name, "\\:") || names[name] {
			return nil, scan, errors.New("unsafe_archive_path")
		}
		for _, part := range strings.Split(strings.TrimRight(name, "/"), "/") {
			if part == "" || part == "." || part == ".." {
				return nil, scan, errors.New("unsafe_archive_path")
			}
		}
		names[name] = true
		switch (f.ExternalAttrs >> 16) & 0170000 {
		case 0, 0100000, 0040000:
		default:
			return nil, scan, errors.New("unsafe_archive_entry")
		}
		if f.Flags&1 != 0 {
			return nil, scan, errors.New("encrypted_archive_entry")
		}
		if f.UncompressedSize64 > 1<<30 {
			return nil, scan, errors.New("archive_member_too_large")
		}
		scan.ExpandedBytes += f.UncompressedSize64
		if scan.ExpandedBytes > 5<<30 {
			return nil, scan, errors.New("archive_too_large")
		}
		if float64(f.UncompressedSize64)/float64(max(f.CompressedSize64, 1)) > 1000 {
			return nil, scan, errors.New("archive_compression_ratio")
		}
		if strings.HasSuffix(path.Base(name), "summarizedActivities.json") {
			members = append(members, f)
			scan.MemberName = name
		}
	}
	if len(members) != 1 {
		return nil, scan, errors.New("activity_member_count")
	}
	scan.MemberCount = len(names)
	return members[0], scan, nil
}

func readExportMember(r *zipinput.Reader, f *zip.File, w io.Writer, code string) error {
	src, err := r.OpenMember(f)
	if err != nil {
		return errors.New(code)
	}
	checksum := crc32.NewIEEE()
	n, readErr := io.Copy(io.MultiWriter(w, checksum), io.LimitReader(src, int64(f.UncompressedSize64)+1))
	closeErr := src.Close()
	if readErr != nil || closeErr != nil || checksum.Sum32() != f.CRC32 {
		return errors.New(code)
	}
	if uint64(n) != f.UncompressedSize64 {
		return errors.New("archive_member_size_mismatch")
	}
	return nil
}

func exportRows(data []byte) ([]any, error) {
	if !json.Valid(data) {
		return nil, errors.New("invalid_activity_json")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	var doc any
	if err := d.Decode(&doc); err != nil {
		return nil, errors.New("invalid_activity_json")
	}
	list, ok := doc.([]any)
	if !ok || len(list) != 1 {
		return nil, errors.New("invalid_activity_schema")
	}
	object, _ := list[0].(map[string]any)
	rows, ok := object["summarizedActivitiesExport"].([]any)
	if !ok {
		return nil, errors.New("invalid_activity_schema")
	}
	return rows, nil
}

func exportActivity(row map[string]any) (map[string]any, string, string, error) {
	id, validID := stringID(row["activityId"])
	owner, validOwner := stringID(row["userProfileId"])
	if !validID || !validOwner || strings.HasPrefix(id, "-") || strings.HasPrefix(owner, "-") || id == "0" || owner == "0" {
		return nil, "", "", errors.New("invalid_activity_identity")
	}
	ms, err := nonnegative(row["startTimeGmt"], "invalid_activity_start")
	if err != nil || ms < 946684800000 || ms >= 4133980800000 {
		return nil, "", "", errors.New("invalid_activity_start")
	}
	seconds, frac := math.Modf(ms / 1000)
	t := time.Unix(int64(seconds), int64(math.RoundToEven(frac*1e6))*1000).UTC()
	if t.Year() < 2000 || t.Year() > 2100 {
		return nil, "", "", errors.New("invalid_activity_start")
	}
	kind, ok := row["activityType"].(string)
	if !ok || kind == "" {
		return nil, "", "", errors.New("invalid_activity_type")
	}
	rec := map[string]any{"activityId": row["activityId"], "ownerId": row["userProfileId"], "startTimeGMT": utcISO(t), "activityType": map[string]any{"typeKey": kind}}
	for _, metric := range []struct {
		src, dst string
		scale    float64
	}{
		{"distance", "distance", 0.01}, {"elapsedDuration", "elapsedDuration", 0.001}, {"movingDuration", "movingDuration", 0.001}, {"avgHr", "averageHR", 1},
	} {
		if raw := row[metric.src]; raw != nil {
			n, err := nonnegative(raw, "invalid_activity_"+metric.src)
			if err != nil {
				return nil, "", "", err
			}
			rec[metric.dst] = n * metric.scale
		}
	}
	return rec, owner, id, nil
}

func exportMetadata(archiveHash, memberHash, start string, index int) map[string]any {
	return map[string]any{"archive_sha256": archiveHash, "member_sha256": memberHash, "row_index": index,
		"field_paths":      map[string]string{"start_at": "startTimeGmt", "original_start": "startTimeGmt", "local_date": "startTimeGmt", "sport": "activityType", "subtype": "activityType", "distance_m": "distance", "elapsed_s": "elapsedDuration", "moving_s": "movingDuration", "avg_hr_bpm": "avgHr"},
		"unit_conversions": map[string]string{"distance_m": "centimeters_to_meters", "elapsed_s": "milliseconds_to_seconds", "moving_s": "milliseconds_to_seconds"},
		"original_start":   start, "source_timezone": "garmin_export_GMT_epoch_ms"}
}

// ScanExport verifies an account-export activity summary and prepares its original
// and normalized records, member bytes and provenance for transactional replay.
func ScanExport(archive []byte) (ExportScan, error) {
	empty := ExportScan{}
	reader, err := zipinput.New(archive)
	if err != nil {
		return empty, errors.New("invalid_export_archive")
	}
	member, scan, err := exportInventory(reader)
	if err != nil {
		return empty, err
	}
	var buf bytes.Buffer
	if err := readExportMember(reader, member, &buf, "invalid_export_archive"); err != nil {
		return empty, err
	}
	scan.MemberBytes = buf.Bytes()
	rows, err := exportRows(scan.MemberBytes)
	if err != nil {
		return empty, err
	}
	archiveHash := fmt.Sprintf("%x", sha256.Sum256(archive))
	memberHash := fmt.Sprintf("%x", sha256.Sum256(scan.MemberBytes))
	seen := map[string]bool{}
	owners := map[string]bool{}
	for index, raw := range rows {
		row, ok := raw.(map[string]any)
		if !ok {
			return empty, errors.New("invalid_activity_record")
		}
		rec, owner, id, err := exportActivity(row)
		if err != nil {
			return empty, err
		}
		if seen[id] {
			return empty, errors.New("duplicate_activity_id")
		}
		seen[id], owners[owner] = true, true
		scan.Owner = owner
		start, err := canonicaljson.Coaching(row["startTimeGmt"])
		if err != nil {
			return empty, errors.New("invalid_activity_start")
		}
		scan.Records = append(scan.Records, ActivityRecord{Original: row, Record: rec, Metadata: exportMetadata(archiveHash, memberHash, string(start), index)})
	}
	if len(owners) != 1 {
		return empty, errors.New("mixed_activity_owner")
	}
	// Python validates CRCs for every archive member before retaining anything.
	for _, f := range reader.File {
		if f != member {
			if err := readExportMember(reader, f, io.Discard, "archive_crc_mismatch"); err != nil {
				return empty, err
			}
		}
	}
	return scan, nil
}
