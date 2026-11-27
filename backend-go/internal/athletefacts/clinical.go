// Package athletefacts interprets current and historical profile facts.
package athletefacts

import (
	"encoding/json"
	"strings"
	"unicode"
)

func trimFact(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f })
}

func ClinicalRestriction(current, legacy *string, flag json.RawMessage) *string {
	for _, v := range []*string{current, legacy} {
		if v == nil {
			continue
		}
		s := trimFact(*v)
		if s != "" && !strings.EqualFold(s, "unknown") && !strings.EqualFold(s, "none") {
			return &s
		}
	}
	var value any
	if json.Unmarshal(flag, &value) != nil {
		return nil
	}
	active := true
	switch v := value.(type) {
	case nil:
		active = false
	case bool:
		active = v
	case string:
		active = v != ""
	case float64:
		active = v != 0
	case map[string]any:
		active = len(v) > 0
	case []any:
		active = len(v) > 0
	}
	if active {
		s := "restricted"
		return &s
	}
	return nil
}
