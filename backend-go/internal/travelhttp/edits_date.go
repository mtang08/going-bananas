package travelhttp

import (
	"encoding/json"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const dateErrorPrefix = "Input should be a valid date or datetime, "
const dateMidnight = "Datetimes provided to dates should have zero time - e.g. be exact dates"

var timestampNumber = regexp.MustCompile(`^[+-]?[0-9]+(?:\.[0-9]+)?$`)

func unixDate(s string) (string, string) {
	n, _ := strconv.ParseFloat(s, 64)
	if math.Abs(n) > 2e10 {
		n /= 1000
	}
	if n >= 253402300800 {
		return "", dateErrorPrefix + "dates after 9999 are not supported as unix timestamps"
	}
	if n < -62135596800 {
		return "", dateErrorPrefix + "dates before 0000 are not supported as unix timestamps"
	}
	sec, frac := math.Modf(n)
	t := time.Unix(int64(sec), int64(math.Round(frac*1e6))*1000).UTC()
	if t.Hour() != 0 || t.Minute() != 0 || t.Second() != 0 || t.Nanosecond() != 0 {
		return "", dateMidnight
	}
	return t.Format(time.DateOnly), ""
}

func inputDate(v any) (string, string) {
	var s string
	switch x := v.(type) {
	case json.Number:
		return unixDate(x.String())
	case string:
		s = x
	default:
		return "", "Input should be a valid date"
	}
	if timestampNumber.MatchString(s) {
		return unixDate(s)
	}
	if len(s) < 10 {
		return "", dateErrorPrefix + "input is too short"
	}
	day := s[:10]
	for _, p := range []struct {
		start, end int
		name       string
	}{{0, 4, "year"}, {5, 7, "month"}, {8, 10, "day"}} {
		if p.start > 0 && day[p.start-1] != '-' {
			return "", dateErrorPrefix + "invalid date separator, expected `-`"
		}
		for _, r := range day[p.start:p.end] {
			if r < '0' || r > '9' {
				return "", dateErrorPrefix + "invalid character in " + p.name
			}
		}
	}
	if day[5:7] < "01" || day[5:7] > "12" {
		return "", dateErrorPrefix + "month value is outside expected range of 1-12"
	}
	if _, err := time.Parse(time.DateOnly, day); err != nil {
		return "", dateErrorPrefix + "day value is outside expected range"
	}
	if len(s) > 10 {
		if !strings.ContainsRune("Tt _", rune(s[10])) {
			return "", dateErrorPrefix + "invalid datetime separator, expected `T`, `t`, `_` or space"
		}
		if msg := midnightTime(s[11:]); msg != "" {
			return "", msg
		}
	}
	if day[:4] == "0000" {
		return "", "Input should be a valid date in the format YYYY-MM-DD, year 0 is out of range"
	}
	return day, ""
}

func timePart(s, name string, max int) (int, string) {
	if len(s) < 2 {
		return 0, dateErrorPrefix + "input is too short"
	}
	if s[0] < '0' || s[0] > '9' || s[1] < '0' || s[1] > '9' {
		return 0, dateErrorPrefix + "invalid character in " + name
	}
	n, _ := strconv.Atoi(s[:2])
	if n > max {
		return 0, dateErrorPrefix + name + " value is outside expected range of 0-" + strconv.Itoa(max)
	}
	return n, ""
}

func midnightTime(s string) string {
	h, msg := timePart(s, "hour", 23)
	if msg != "" {
		return msg
	}
	if len(s) < 3 {
		return dateErrorPrefix + "input is too short"
	}
	if s[2] != ':' {
		return dateErrorPrefix + "invalid time separator, expected `:`"
	}
	m, msg := timePart(s[3:], "minute", 59)
	if msg != "" {
		return msg
	}
	s = s[5:]
	second := 0
	var fraction string
	if strings.HasPrefix(s, ":") {
		second, msg = timePart(s[1:], "second", 59)
		if msg != "" {
			return msg
		}
		s = s[3:]
		if strings.HasPrefix(s, ".") || strings.HasPrefix(s, ",") {
			s = s[1:]
			n := 0
			for n < len(s) && s[n] >= '0' && s[n] <= '9' {
				n++
			}
			if n == 0 {
				return dateErrorPrefix + "second fraction value is missing after decimal"
			}
			fraction = s[:min(n, 6)]
			s = s[n:]
		}
	}
	if s != "" && s != "Z" && s != "z" {
		if s[0] != '+' && s[0] != '-' {
			return dateErrorPrefix + "invalid timezone sign"
		}
		if _, msg = timePart(s[1:], "timezone hour", 99); msg != "" {
			return msg
		}
		hour, _ := strconv.Atoi(s[1:3])
		rest := strings.TrimPrefix(s[3:], ":")
		if len(rest) != 2 {
			return dateErrorPrefix + "unexpected extra characters at the end of the input"
		}
		minute, msg := timePart(rest, "timezone minute", 59)
		if msg != "" {
			return msg
		}
		if hour*60+minute >= 24*60 {
			return dateErrorPrefix + "timezone offset must be less than 24 hours"
		}
	}
	if h+m+second != 0 || strings.Trim(fraction, "0") != "" {
		return dateMidnight
	}
	return ""
}
