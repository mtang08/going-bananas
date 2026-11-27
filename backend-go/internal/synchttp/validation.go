package synchttp

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

func object(r *http.Request) (map[string]any, error) {
	b, err := io.ReadAll(r.Body)
	if err != nil || len(b) == 0 || string(bytes.TrimSpace(b)) == "null" {
		return nil, invalid([]field{{"body", "Field required"}})
	}
	var raw json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		pos := len(b)
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) && syntax.Offset > 0 && err.Error() != "unexpected end of JSON input" {
			pos = int(syntax.Offset) - 1
		}
		return nil, invalid([]field{{fmt.Sprintf("body.%d", utf8.RuneCount(b[:pos])), "JSON decode error"}})
	}
	if raw[0] != '{' {
		return nil, invalid([]field{{"body", "Input should be a valid dictionary or object to extract fields from"}})
	}
	var out map[string]any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	err = d.Decode(&out)
	return out, err
}

var intText = regexp.MustCompile(`^[+-]?[0-9](_?[0-9])*(\.0+)?$`)
var floatText = regexp.MustCompile(`(?i)^[+-]?(?:(?:[0-9](_?[0-9])*(?:\.(?:[0-9](_?[0-9])*)?)?|\.[0-9](_?[0-9])*)(?:e[+-]?[0-9](_?[0-9])*)?|inf(?:inity)?|nan)$`)

func numeric(v any, integer bool) (float64, string) {
	var s string
	switch x := v.(type) {
	case bool:
		if x {
			return 1, ""
		}
		s = "0"
	case string:
		s = strings.TrimSpace(x)
		if integer && !intText.MatchString(s) {
			return 0, "Input should be a valid integer, unable to parse string as an integer"
		}
		if !integer && !floatText.MatchString(s) {
			return 0, "Input should be a valid number, unable to parse string as a number"
		}
		s = strings.ReplaceAll(s, "_", "")
	case json.Number:
		s = string(x)
	default:
		if integer {
			return 0, "Input should be a valid integer"
		}
		return 0, "Input should be a valid number"
	}
	n, err := strconv.ParseFloat(s, 64)
	if err != nil {
		if integer {
			return 0, "Input should be a valid integer, unable to parse string as an integer"
		}
		return 0, "Input should be a valid number, unable to parse string as a number"
	}
	if math.IsInf(n, 0) || math.IsNaN(n) {
		return 0, "Input should be a finite number"
	}
	if integer && n != math.Trunc(n) {
		if _, ok := v.(string); ok {
			return 0, "Input should be a valid integer, unable to parse string as an integer"
		}
		return 0, "Input should be a valid integer, got a number with a fractional part"
	}
	if integer && n < 0 {
		return 0, "Input should be greater than or equal to 0"
	}
	if !integer && n < 1 {
		return 0, "Input should be greater than or equal to 1"
	}
	return n, ""
}
func confirmation(r *http.Request) (string, map[int]float64, error) {
	obj, err := object(r)
	if err != nil {
		return "", nil, err
	}
	var fields []field
	var token string
	raw, ok := obj["preview_token"]
	if !ok {
		fields = append(fields, field{"body.preview_token", "Field required"})
	} else if s, ok := raw.(string); !ok {
		fields = append(fields, field{"body.preview_token", "Input should be a valid string"})
	} else {
		token = s
		if len(s) == 0 {
			fields = append(fields, field{"body.preview_token", "String should have at least 1 character"})
		} else if utf8.RuneCountInString(s) > 64 {
			fields = append(fields, field{"body.preview_token", "String should have at most 64 characters"})
		}
	}
	paces := map[int]float64{}
	raw, ok = obj["paces"]
	if !ok {
		fields = append(fields, field{"body.paces", "Field required"})
	} else if items, ok := raw.([]any); !ok {
		fields = append(fields, field{"body.paces", "Input should be a valid list"})
	} else {
		for i, item := range items {
			base := fmt.Sprintf("body.paces.%d", i)
			p, ok := item.(map[string]any)
			if !ok {
				fields = append(fields, field{base, "Input should be a valid dictionary or object to extract fields from"})
				continue
			}
			var nums [2]float64
			for j, k := range []string{"lap_index", "pace_seconds_per_mile"} {
				v, ok := p[k]
				if !ok {
					fields = append(fields, field{base + "." + k, "Field required"})
					continue
				}
				n, msg := numeric(v, j == 0)
				if msg != "" {
					fields = append(fields, field{base + "." + k, msg})
				}
				nums[j] = n
			}
			paces[int(nums[0])] = nums[1]
		}
		if len(fields) == 0 && len(paces) != len(items) {
			fields = append(fields, field{"body", "Value error, duplicate_treadmill_lap"})
		}
	}
	if len(fields) > 0 {
		return "", nil, invalid(fields)
	}
	return token, paces, nil
}
