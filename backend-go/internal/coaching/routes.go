package coaching

import (
	"errors"
	"slices"
	"unicode/utf8"
)

var topicPaths = []string{
	"topics/ptt_and_load_tolerance.md", "topics/recovery_and_daily_adaptation.md",
	"topics/hybrid_strength_and_scheduling.md", "topics/long_runs_and_race_development.md",
	"topics/aerobic_progression.md", "topics/intensity_and_workout_methods.md",
	"topics/intensity_calibration_and_testing.md", "topics/periodization_and_training_blocks.md",
	"topics/races_tapers_and_transitions.md", "topics/travel_and_time_zones.md",
}

func ConditionalTopics() []string { return slices.Clone(topicPaths) }

var routePolicies = map[string][]string{
	"proceed_or_modify_today":    {"P001", "P002", "P004", "P005", "P006", "P012", "P013", "P015", "P018"},
	"review_rolling_plan":        {"P001", "P003", "P006", "P007", "P008", "P009", "P010", "P012", "P013", "P014", "P015", "P016", "P017"},
	"select_quality_session":     {"P009", "P014", "P015", "P020"},
	"review_training_block":      {"P003", "P007", "P009", "P014", "P019", "P021", "P028"},
	"recalibrate_intensity":      {"P010", "P015", "P020", "P021"},
	"handle_goal_or_race_change": {"P019", "P022", "P023"},
	"exception_review":           {"P001", "P002", "P003", "P004", "P005", "P006", "P013", "P015", "P018", "P024", "P025", "P026"},
	"post_event_review":          {"P006", "P013", "P018", "P020", "P021", "P026", "P027"},
}

type Route struct {
	Knowledge VerifiedKnowledge
	Excerpts  []map[string]any
	Version   string
	Chars     int
}

type excerptKey struct{ path, value string }

func LoadRoute(root, operation string, recipeIDs, topics []string) (Route, error) {
	pids, ok := routePolicies[operation]
	if !ok {
		return Route{}, errors.New("unsupported operation")
	}
	manifest, files, index, err := knowledgeFiles(root)
	if err != nil {
		return Route{}, err
	}
	routing, _ := manifest["routing"].(map[string]any)
	spec, _ := routing[operation].(map[string]any)
	minimum, ok := spec["minimum"].([]any)
	if !ok {
		return Route{}, errors.New("missing knowledge route")
	}
	var entries []excerptKey
	for _, v := range minimum {
		item, ok := v.(map[string]any)
		if !ok {
			return Route{}, errors.New("invalid knowledge route")
		}
		path, _ := item["path"].(string)
		sections, ok := item["sections"].([]any)
		if !ok {
			if _, state := item["state"]; !state && item["records"] == nil {
				return Route{}, errors.New("invalid knowledge route item")
			}
			continue
		}
		for _, v := range sections {
			s, ok := v.(string)
			if !ok {
				return Route{}, errors.New("invalid knowledge section")
			}
			entries = append(entries, excerptKey{path, s})
		}
	}
	for _, p := range topics {
		if !slices.Contains(topicPaths, p) {
			return Route{}, errors.New("unknown conditional topic")
		}
	}
	for _, path := range topicPaths {
		if !slices.Contains(topics, path) {
			continue
		}
		i := slices.IndexFunc(entries, func(e excerptKey) bool { return e.path == path })
		entries = slices.DeleteFunc(entries, func(e excerptKey) bool { return e.path == path })
		if i < 0 {
			i = len(entries)
		}
		entries = slices.Insert(entries, i, excerptKey{path, "*"})
	}
	ids := slices.Clone(recipeIDs)
	slices.Sort(ids)
	for _, rid := range slices.Compact(ids) {
		if !index.RecipeIDs[rid] {
			return Route{}, errors.New("unknown recipe")
		}
		entries = append(entries, excerptKey{recipes, rid})
	}
	for _, id := range pids {
		i := slices.IndexFunc(policies, func(p string) bool { _, ok := files[p].records[id]; return ok })
		if i < 0 {
			return Route{}, errors.New("missing policy")
		}
		entries = append(entries, excerptKey{policies[i], id})
	}
	selection := []SelectionEntry{}
	indices := map[string]int{}
	for _, e := range entries {
		i, ok := indices[e.path]
		if !ok {
			i = len(selection)
			indices[e.path] = i
			selection = append(selection, SelectionEntry{Path: e.path})
		}
		s := &selection[i]
		if e.path == recipes || slices.Contains(policies, e.path) {
			s.RecordIDs = append(s.RecordIDs, e.value)
		} else {
			s.Sections = append(s.Sections, e.value)
		}
	}
	texts := map[excerptKey]string{}
	verified, _, err := verifyLoadedSelection(manifest, files, index, selection, texts)
	if err != nil {
		return Route{}, err
	}
	route := Route{Version: index.PackageVersion, Knowledge: verified, Excerpts: []map[string]any{}}
	for _, e := range entries {
		text := texts[e]
		v := map[string]any{"path": e.path, "text": text}
		if e.path == recipes || slices.Contains(policies, e.path) {
			v["record_id"] = e.value
		} else if e.value != "*" {
			v["section"] = e.value
		}
		route.Excerpts = append(route.Excerpts, v)
		route.Chars += utf8.RuneCountInString(text)
	}
	return route, nil
}
