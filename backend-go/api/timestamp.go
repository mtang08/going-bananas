package api

import (
	"strconv"
	"time"
)

// Timestamp preserves FastAPI's database session offset and microsecond precision.
type Timestamp time.Time

func (t Timestamp) MarshalJSON() ([]byte, error) {
	v := time.Time(t)
	layout := "2006-01-02T15:04:05Z07:00"
	if v.Nanosecond() != 0 {
		layout = "2006-01-02T15:04:05.000000Z07:00"
	}
	return []byte(strconv.Quote(v.Format(layout))), nil
}

func (t *Timestamp) UnmarshalJSON(data []byte) error {
	var v time.Time
	if err := v.UnmarshalJSON(data); err != nil {
		return err
	}
	*t = Timestamp(v)
	return nil
}
