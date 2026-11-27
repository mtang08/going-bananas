package activityhttp

import (
	"cmp"
	"context"
	"maps"
	"net/http"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
)

func metricDates(r *http.Request, required bool, loc *time.Location) (first, last time.Time, err error) {
	var fields []object
	for _, item := range []struct {
		name string
		dst  *time.Time
	}{{"start", &first}, {"end", &last}} {
		raw, ok := parameter(r.URL.Query(), item.name)
		if !ok && !required {
			continue
		}
		parsed, msg := httpinput.Date(raw)
		if !ok {
			msg = "Field required"
		}
		if msg != "" {
			fields = append(fields, object{"field": "query." + item.name, "message": msg})
			continue
		}
		*item.dst, err = time.ParseInLocation(time.DateOnly, parsed, loc)
		if err != nil {
			return
		}
	}
	if len(fields) > 0 {
		err = &problem{422, "validation_error", "Invalid request fields", fields}
	}
	return
}

func (h Handler) progression(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	first, last, dateErr := metricDates(r, false, loc)
	groupBy, ok := parameter(r.URL.Query(), "group_by")
	if !ok {
		groupBy = "signature"
	}
	var groupErr error
	if groupBy != "signature" && groupBy != "recipe" {
		groupErr = invalid("query.group_by", "Input should be 'signature' or 'recipe'")
	}
	if err := bindingErrors(dateErr, groupErr); err != nil {
		return nil, err
	}
	local := now.In(loc)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, loc)
	if last.IsZero() || last.After(today) {
		last = today
	}
	if first.IsZero() {
		first = last.AddDate(0, 0, -179)
	}
	if first.After(last) || !last.Before(first.AddDate(0, 0, 366)) {
		return nil, &problem{422, "invalid_date_window", "Invalid date window", nil}
	}
	points, err := progressionPoints(ctx, tx, first, last, loc)
	if err != nil {
		return nil, err
	}
	return object{"start": first.Format(time.DateOnly), "end": last.Format(time.DateOnly), "group_by": groupBy, "groups": groupPoints(points, groupBy)}, nil
}

func groupPoints(points []object, mode string) []object {
	groups := map[string][]object{}
	for _, p := range points {
		key := "sig:" + p["signature"].(string)
		if recipe, _ := p["recipe_id"].(*string); mode == "recipe" && recipe != nil && *recipe != "" {
			key = "recipe:" + *recipe
		}
		groups[key] = append(groups[key], p)
	}
	result := []object{}
	for key, items := range groups {
		recipes, signatures := map[string]bool{}, map[string]bool{}
		assessable := 0
		for _, p := range items {
			signatures[p["signature"].(string)] = true
			if recipe, _ := p["recipe_id"].(*string); recipe != nil && *recipe != "" {
				recipes[*recipe] = true
			}
			if p["status"] == "available" || p["status"] == "partial" {
				assessable++
			}
		}
		signature := items[0]["signature"]
		groupBy := "signature"
		if strings.HasPrefix(key, "recipe:") {
			signature = nil
			groupBy = "recipe"
		}
		recipeIDs := slices.Sorted(maps.Keys(recipes))
		if recipeIDs == nil {
			recipeIDs = []string{}
		}
		result = append(result, object{"group_key": key, "group_by": groupBy, "signature": signature, "signatures": slices.Sorted(maps.Keys(signatures)), "recipe_ids": recipeIDs, "sessions_total": len(items), "sessions_assessable": assessable, "latest_date": items[len(items)-1]["local_date"], "points": items})
	}
	slices.SortFunc(result, func(a, b object) int {
		return cmp.Or(strings.Compare(b["latest_date"].(string), a["latest_date"].(string)), strings.Compare(b["group_key"].(string), a["group_key"].(string)))
	})
	return result
}
