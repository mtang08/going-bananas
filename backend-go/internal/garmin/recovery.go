package garmin

import (
	"context"
	"errors"
	"net/url"
	"time"
)

func (c *Client) FetchRecovery(ctx context.Context, dataset string, first, last time.Time) ([]Record, error) {
	start, end := first.Format(time.DateOnly), last.Format(time.DateOnly)
	switch dataset {
	case "sleep":
		var rows []Record
		if err := c.readJSON(ctx, "/sleep-service/sleep/dailySleepSummariesByDate", dateRange(first, last), &rows); err != nil {
			return nil, recordShape(err, "invalid_sleep_shape")
		}
		if !validRecords(rows) {
			return nil, errors.New("invalid_sleep_shape")
		}
		return rows, nil
	case "hrv":
		var response struct {
			Owner any      `json:"userProfilePk"`
			Rows  []Record `json:"hrvSummaries"`
		}
		if err := c.readJSON(ctx, "/hrv-service/hrv/daily/"+start+"/"+end, nil, &response); err != nil {
			return nil, recordShape(err, "invalid_hrv_shape")
		}
		if !validRecords(response.Rows) {
			return nil, errors.New("invalid_hrv_shape")
		}
		for _, row := range response.Rows {
			row["userProfilePk"] = response.Owner
		}
		return response.Rows, nil
	case "resting_hr":
		rows := []Record{}
		for d := first; d.Format(time.DateOnly) <= end; d = d.AddDate(0, 0, 1) {
			var row Record
			if err := c.readJSON(ctx, "/wellness-service/wellness/dailyHeartRate", url.Values{"date": {d.Format(time.DateOnly)}}, &row); err != nil {
				return nil, recordShape(err, "invalid_resting_hr_shape")
			}
			if row == nil {
				return nil, errors.New("invalid_resting_hr_shape")
			}
			rows = append(rows, row)
		}
		return rows, nil
	default:
		return nil, errors.New("unsupported_dataset")
	}
}
