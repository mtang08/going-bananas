package garmin

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"iter"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type Record map[string]any
type Page struct {
	Offset  int
	Records []Record
}

func (c *Client) readJSON(ctx context.Context, path string, query url.Values, dst any) error {
	body, err := c.get(ctx, path, query, "application/json")
	if err != nil || len(body) == 0 {
		return err
	}
	if !json.Valid(body) {
		return errors.New("invalid_garmin_json")
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber() // Garmin activity and profile IDs must keep their original precision.
	return dec.Decode(dst)
}

func recordShape(err error, code string) error {
	var mismatch *json.UnmarshalTypeError
	if errors.As(err, &mismatch) {
		return errors.New(code)
	}
	return err
}

func dateRange(first, last time.Time) url.Values {
	return url.Values{"startDate": {first.Format(time.DateOnly)}, "endDate": {last.Format(time.DateOnly)}}
}

func (c *Client) SearchPage(ctx context.Context, start, limit int, first, last time.Time) ([]Record, error) {
	q := dateRange(first, last)
	q.Set("start", strconv.Itoa(start))
	q.Set("limit", strconv.Itoa(limit))
	var rows []Record
	if err := c.readJSON(ctx, "/activitylist-service/activities/search/activities", q, &rows); err != nil {
		return nil, recordShape(err, "invalid_activity_page_shape")
	}
	if !validRecords(rows) {
		return nil, errors.New("invalid_activity_page_shape")
	}
	return rows, nil
}

func validRecords(rows []Record) bool {
	if rows == nil {
		return false
	}
	for _, r := range rows {
		if r == nil {
			return false
		}
	}
	return true
}

func pageSignature(rows []Record) string {
	var key strings.Builder
	for _, row := range rows {
		id := fmt.Sprint(row["activityId"])
		fmt.Fprintf(&key, "%d:%s", len(id), id)
	}
	return key.String()
}

// Pages yields the terminal short page, including an empty one. Callers can stop
// iterating before the next network request.
func (c *Client) Pages(ctx context.Context, first, last time.Time, pageSize, maxPages int) iter.Seq2[Page, error] {
	return func(yield func(Page, error) bool) {
		if first.Format(time.DateOnly) > last.Format(time.DateOnly) {
			yield(Page{}, errors.New("inverted_date_range"))
			return
		}
		if pageSize < 1 || pageSize > 200 || maxPages < 1 {
			yield(Page{}, errors.New("invalid_paging_limit"))
			return
		}
		seen := map[string]bool{}
		for n := range maxPages {
			offset := n * pageSize
			rows, err := c.SearchPage(ctx, offset, pageSize, first, last)
			if err != nil {
				yield(Page{}, err)
				return
			}
			key := pageSignature(rows)
			if len(rows) > 0 && seen[key] {
				yield(Page{}, errors.New("repeated_activity_page"))
				return
			}
			seen[key] = true
			if !yield(Page{offset, rows}, nil) || len(rows) < pageSize {
				return
			}
		}
		yield(Page{}, errors.New("activity_page_limit"))
	}
}

func (c *Client) ActivityDetail(ctx context.Context, id string) (any, error) {
	var value any
	err := c.readJSON(ctx, "/activity-service/activity/"+url.PathEscape(id), nil, &value)
	return value, err
}
func (c *Client) ActivityWorkouts(ctx context.Context, id string) (any, error) {
	var value any
	err := c.readJSON(ctx, "/activity-service/activity/"+url.PathEscape(id)+"/workouts", nil, &value)
	return value, err
}
func (c *Client) DownloadActivity(ctx context.Context, id string) ([]byte, error) {
	if strings.Trim(id, "0123456789") != "" || strings.Trim(id, "0") == "" {
		return nil, errors.New("activity_id must be a positive integer")
	}
	b, err := c.get(ctx, "/download-service/files/activity/"+id, nil, "application/zip, application/x-zip-compressed, application/octet-stream")
	if err == nil && len(b) == 0 {
		return nil, errors.New("empty_activity_download")
	}
	return b, err
}
