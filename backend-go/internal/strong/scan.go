// Package strong previews and applies local Strong CSV exports.
package strong

import (
	"bytes"
	"cmp"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
)

const maxBytes = 100_000_000
const maxRows = 250_000

var columns = []string{"Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight", "Reps", "Distance", "Seconds", "RPE"}

type Workout struct {
	SourceIdentity string              `json:"source_identity"`
	PayloadHash    string              `json:"payload_hash"`
	LocalStart     string              `json:"local_start"`
	LocalDate      string              `json:"local_date"`
	WorkoutName    string              `json:"workout_name"`
	DurationS      *int                `json:"duration_s"`
	Sets           []map[string]string `json:"sets"`
	RowCount       int                 `json:"row_count"`
}
type Scan struct {
	Workouts []Workout
	Digest   string
	bytes    []byte
}
type Error string

func (e Error) Error() string { return string(e) }
func hash(b []byte) string    { return fmt.Sprintf("%x", sha256.Sum256(b)) }

// csvRow implements Strong's Excel CSV dialect. Go's encoding/csv rewrites
// CRLF inside quoted fields. Those characters are part of Strong's source hash.
func csvRow(data []byte) (row []string, consumed int, err error) {
	var field []byte
	quoted := false
	for i := 0; i < len(data); i++ {
		ch := data[i]
		if quoted {
			if ch != '"' {
				field = append(field, ch)
				continue
			}
			if i+1 < len(data) && data[i+1] == '"' {
				field = append(field, '"')
				i++
				continue
			}
			quoted = false
			continue
		}
		switch ch {
		case '"':
			if len(field) == 0 && (i == 0 || data[i-1] == ',') {
				quoted = true
			} else {
				field = append(field, ch)
			}
		case ',':
			row = append(row, string(field))
			field = field[:0]
		case '\n', '\r':
			n := i + 1
			if ch == '\r' && n < len(data) && data[n] == '\n' {
				n++
			}
			if i == 0 {
				return nil, n, nil
			}
			return append(row, string(field)), n, nil
		default:
			field = append(field, ch)
		}
	}
	if len(data) > 0 {
		return append(row, string(field)), len(data), nil
	}
	return nil, 0, io.EOF
}

var durationPattern = regexp.MustCompile(`^(?:([0-9]+)h\s*)?(?:([0-9]+)m\s*)?(?:([0-9]+)s)?$`)

func duration(text string) (*int, error) {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil, nil
	}
	parts := durationPattern.FindStringSubmatch(text)
	if parts == nil {
		return nil, Error("invalid_duration")
	}
	total := 0
	for i, factor := range []int{3600, 60, 1} {
		p := parts[i+1]
		if p == "" {
			continue
		}
		n, err := strconv.ParseUint(p, 10, 64)
		if err != nil || n > 86400 {
			return nil, nil
		}
		total += int(n) * factor
	}
	if total > 86400 {
		return nil, nil
	}
	return &total, nil
}

var stampPattern = regexp.MustCompile(`^([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})\s+([0-9]{1,2}):([0-9]{1,2}):([0-9]{1,2})$`)

func stamp(text string) (string, error) {
	p := stampPattern.FindStringSubmatch(text)
	if p == nil {
		return "", Error("invalid_date")
	}
	var n [6]int
	for i := range n {
		n[i], _ = strconv.Atoi(p[i+1])
	}
	t := time.Date(n[0], time.Month(n[1]), n[2], n[3], n[4], n[5], 0, time.UTC)
	if n[0] == 0 || t.Year() != n[0] || int(t.Month()) != n[1] || t.Day() != n[2] || t.Hour() != n[3] || t.Minute() != n[4] || t.Second() != n[5] {
		return "", Error("invalid_date")
	}
	return t.Format("2006-01-02 15:04:05"), nil
}

var numeric = regexp.MustCompile(`^[+-]?(?:(?:[0-9](?:_?[0-9])*)(?:\.(?:[0-9](?:_?[0-9])*)?)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?$`)

func newSet(row []string) (string, *int, error) {
	if len(row) != len(columns) {
		return "", nil, Error("malformed_row")
	}
	start, err := stamp(row[0])
	if err != nil {
		return "", nil, err
	}
	if strings.TrimSpace(row[1]) == "" || strings.TrimSpace(row[3]) == "" {
		return "", nil, Error("missing_name")
	}
	for _, raw := range row[5:] {
		v := strings.TrimSpace(raw)
		if v == "" {
			continue
		}
		if !numeric.MatchString(v) {
			return "", nil, Error("invalid_number")
		}
		n, _ := strconv.ParseFloat(strings.ReplaceAll(v, "_", ""), 64)
		if math.IsNaN(n) || n < 0 || n >= 1_000_000 {
			return "", nil, Error("invalid_number")
		}
	}
	order := row[4]
	if order != "W" && order != "F" {
		n, err := strconv.Atoi(order)
		if err != nil || n < 1 || n > 99 || strconv.Itoa(n) != order {
			return "", nil, Error("invalid_set_order")
		}
	}
	d, err := duration(row[2])
	return start, d, err
}

// Strong hashes use the export's column order for set rows and Python's
// default comma-space separator for the timestamp/name identity.
func workoutHashes(w *Workout) error {
	start, err := canonicaljson.Coaching(w.LocalStart)
	if err != nil {
		return err
	}
	name, err := canonicaljson.Coaching(w.WorkoutName)
	if err != nil {
		return err
	}
	w.SourceIdentity = hash([]byte("[" + string(start) + ", " + string(name) + "]"))
	h := sha256.New()
	_, _ = io.WriteString(h, "[")
	for i, row := range w.Sets {
		if i > 0 {
			_, _ = io.WriteString(h, ",")
		}
		_, _ = io.WriteString(h, "{")
		for j, key := range columns {
			if j > 0 {
				_, _ = io.WriteString(h, ",")
			}
			value, err := canonicaljson.Coaching(row[key])
			if err != nil {
				return err
			}
			_, _ = fmt.Fprintf(h, "%q:", key)
			_, _ = h.Write(value)
		}
		_, _ = io.WriteString(h, "}")
	}
	_, _ = io.WriteString(h, "]")
	w.PayloadHash = fmt.Sprintf("%x", h.Sum(nil))
	return nil
}

func ScanFile(path string) (Scan, error) {
	f, err := os.Open(path)
	if err != nil {
		return Scan{}, Error("csv_io_error")
	}
	defer func() { _ = f.Close() }()
	body, err := io.ReadAll(io.LimitReader(f, maxBytes+1))
	if err != nil {
		return Scan{}, Error("csv_io_error")
	}
	return scan(body, maxRows)
}

func scan(body []byte, limit int) (Scan, error) {
	if len(body) > maxBytes {
		return Scan{}, Error("csv_too_large")
	}
	if !utf8.Valid(body) {
		return Scan{}, Error("invalid_utf8")
	}
	data := bytes.TrimPrefix(body, []byte("\xef\xbb\xbf"))
	header, n, _ := csvRow(data)
	if !slices.Equal(header, columns) {
		return Scan{}, Error("unsupported_columns")
	}
	data = data[n:]
	type group struct{ stamp, name string }
	groups := map[group]*Workout{}
	count := 0
	for len(data) > 0 {
		row, n, err := csvRow(data)
		if err != nil {
			return Scan{}, err
		}
		data = data[n:]
		if len(row) == 0 {
			continue
		}
		count++
		if count > limit {
			return Scan{}, Error("too_many_rows")
		}
		for _, value := range row {
			if utf8.RuneCountInString(value) > 131072 {
				return Scan{}, Error("csv_field_too_large")
			}
		}
		start, d, err := newSet(row)
		if err != nil {
			return Scan{}, err
		}
		key := group{start, row[1]}
		w := groups[key]
		if w == nil {
			w = &Workout{LocalStart: start, LocalDate: start[:10], WorkoutName: row[1], DurationS: d}
			groups[key] = w
		} else if (w.DurationS == nil) != (d == nil) || (d != nil && *w.DurationS != *d) {
			return Scan{}, Error("inconsistent_duration")
		}
		set := make(map[string]string, len(columns))
		for i, k := range columns {
			set[k] = row[i]
		}
		w.Sets = append(w.Sets, set)
		w.RowCount++
	}
	if len(groups) == 0 {
		return Scan{}, Error("empty_csv")
	}
	result := Scan{Digest: hash(body), bytes: body}
	for _, w := range groups {
		if err := workoutHashes(w); err != nil {
			return Scan{}, errors.New("invalid_workout_hash")
		}
		result.Workouts = append(result.Workouts, *w)
	}
	slices.SortFunc(result.Workouts, func(a, b Workout) int {
		return cmp.Or(strings.Compare(a.LocalStart, b.LocalStart), strings.Compare(a.WorkoutName, b.WorkoutName))
	})
	return result, nil
}
