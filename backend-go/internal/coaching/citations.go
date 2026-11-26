package coaching

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
)

type Citation struct {
	Kind   string   `json:"kind"`
	Title  string   `json:"title"`
	Papers []string `json:"papers"`
}

func CitedSources(root string, evidenceIDs, policyIDs []string) ([]Citation, error) {
	_, files, _, err := knowledgeFiles(root)
	if err != nil {
		return nil, err
	}
	var registry struct {
		Sources []struct {
			ID    string `json:"source_id"`
			Title string
			Year  any
		}
	}
	if err := json.Unmarshal(files["references/source_registry.json"].raw, &registry); err != nil {
		return nil, err
	}
	papers := map[string]string{}
	for _, r := range registry.Sources {
		papers[r.ID] = fmt.Sprintf("%s (%v)", r.Title, r.Year)
	}
	out := []Citation{}
	indices := map[[2]string]int{}
	add := func(kind, title string, ids []string) {
		key := [2]string{kind, title}
		i, ok := indices[key]
		if !ok {
			i = len(out)
			indices[key] = i
			out = append(out, Citation{kind, title, []string{}})
		}
		for _, id := range ids {
			if paper := papers[strings.TrimSpace(id)]; paper != "" && !slices.Contains(out[i].Papers, paper) {
				out[i].Papers = append(out[i].Papers, paper)
			}
		}
	}
	for _, id := range policyIDs {
		for _, path := range policies {
			if rec, ok := files[path].records[id]; ok {
				var item struct {
					Title string
					IDs   []string `json:"source_ids"`
				}
				if err := json.Unmarshal(rec.raw, &item); err != nil {
					return nil, err
				}
				add("policy", item.Title, item.IDs)
				break
			}
		}
	}
	evidence := map[string][]string{}
	for _, path := range evidenceFiles {
		for line := range strings.SplitSeq(string(files[path].raw), "\n") {
			if evidenceRow.MatchString(line) {
				cells := strings.Split(strings.Trim(strings.TrimSpace(line), "|"), "|")
				evidence[strings.TrimSpace(cells[0])] = cells
			}
		}
	}
	for _, id := range evidenceIDs {
		if cells := evidence[id]; len(cells) > 1 {
			add("evidence", strings.TrimSpace(cells[1]), strings.Split(cells[len(cells)-1], ";"))
		}
	}
	return out, nil
}
