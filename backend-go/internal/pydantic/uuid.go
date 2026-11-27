package pydantic

import (
	"fmt"
	"strings"

	"github.com/google/uuid"
)

func UUID(raw string) (uuid.UUID, string) {
	const prefix = "Input should be a valid UUID, "
	if id, err := uuid.Parse(raw); err == nil && !strings.HasPrefix(raw, "URN:") && (len(raw) != 38 || raw[0] == '{' && raw[37] == '}') {
		return id, ""
	}
	core := strings.TrimPrefix(raw, "urn:uuid:")
	if strings.HasPrefix(core, "{") && strings.HasSuffix(core, "}") {
		core = core[1 : len(core)-1]
	}
	for i, r := range core {
		if !strings.ContainsRune("0123456789abcdefABCDEF-", r) {
			return uuid.Nil, fmt.Sprintf("%sinvalid character: found `%c` at %d", prefix, r, i+strings.Index(raw, core))
		}
	}
	parts := strings.Split(core, "-")
	if len(parts) == 1 && core == raw {
		return uuid.Nil, fmt.Sprintf("%sinvalid length: found %d", prefix, len(raw))
	}
	if len(parts) != 5 {
		return uuid.Nil, fmt.Sprintf("%sinvalid group count: expected 5, found %d", prefix, len(parts))
	}
	for i, n := range []int{8, 4, 4, 4, 12} {
		if len(parts[i]) != n {
			return uuid.Nil, fmt.Sprintf("%sinvalid group length in group %d: expected %d, found %d", prefix, i, n, len(parts[i]))
		}
	}
	return uuid.Nil, prefix + "invalid UUID"
}
