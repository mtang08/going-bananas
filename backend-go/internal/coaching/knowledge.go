package coaching

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"
)

const maxKnowledgeBytes = 200_000

var policies = []string{"policies/coaching_policy_candidates.json", "policies/periodization_policy_candidates.json"}

const recipes = "recipes/running_session_families.json"

var evidenceFiles = []string{"references/evidence_matrix.md", "references/periodization_evidence_addendum.md"}
var evidenceRow = regexp.MustCompile(`(?m)^\| (E-[A-Z]+-[0-9]{2}) \|`)
var headingLine = regexp.MustCompile(`^(#{1,6})[ \t]+(.+?)[ \t]*$`)

type KnowledgeIndex struct {
	PolicyIDs, RecipeIDs, EvidenceIDs map[string]bool
	PackageVersion                    string
}

type verifiedFile struct {
	raw     []byte
	records map[string]knowledgeRecord
}
type knowledgeRecord struct {
	content RecordContent
	raw     json.RawMessage
}

func boundedFile(root, name string) ([]byte, error) {
	if !fs.ValidPath(name) || name == "." {
		return nil, errors.New("invalid knowledge path")
	}
	full := filepath.Join(root, filepath.FromSlash(name))
	info, err := os.Lstat(full)
	if err != nil {
		return nil, err
	}
	resolved, err := filepath.EvalSymlinks(full)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || !strings.HasPrefix(resolved, root+string(filepath.Separator)) || info.Size() > maxKnowledgeBytes {
		return nil, fmt.Errorf("unsafe knowledge file %q", name)
	}
	file, err := os.Open(full)
	if err != nil {
		return nil, err
	}
	defer func() { _ = file.Close() }()
	b, err := io.ReadAll(io.LimitReader(file, maxKnowledgeBytes+1))
	if err == nil && (len(b) > maxKnowledgeBytes || !utf8.Valid(b)) {
		return nil, fmt.Errorf("invalid knowledge bytes %q", name)
	}
	return b, err
}

func knowledgeFiles(root string) (map[string]any, map[string]verifiedFile, KnowledgeIndex, error) {
	index := KnowledgeIndex{PolicyIDs: map[string]bool{}, RecipeIDs: map[string]bool{}, EvidenceIDs: map[string]bool{}}
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, nil, index, err
	}
	root, err = filepath.EvalSymlinks(root)
	if err != nil {
		return nil, nil, index, err
	}
	raw, err := boundedFile(root, "manifest.json")
	if err != nil {
		return nil, nil, index, err
	}
	var manifest map[string]any
	if err = decodeEvidenceObject(raw, &manifest); err != nil {
		return nil, nil, index, err
	}
	entries, ok := manifest["files"].([]any)
	index.PackageVersion, _ = manifest["package_version"].(string)
	_, routing := manifest["routing"].(map[string]any)
	if !ok || !routing || manifest["schema_version"] != "1.1" || manifest["package_name"] != "running_coach_kb" || index.PackageVersion == "" {
		return nil, nil, index, errors.New("unsupported knowledge manifest")
	}
	files := map[string]verifiedFile{}
	for _, item := range entries {
		rec, _ := item.(map[string]any)
		path, _ := rec["path"].(string)
		size, ok := rec["bytes"].(json.Number)
		count, err := strconv.Atoi(string(size))
		sha, hasSHA := rec["sha256"]
		_, dup := files[path]
		if !fs.ValidPath(path) || path == "." || !ok || err != nil || count < 0 || !hasSHA || dup {
			return nil, nil, index, errors.New("invalid knowledge file record")
		}
		files[path] = verifiedFile{}
		if sha == nil {
			continue
		}
		b, err := boundedFile(root, path)
		if err != nil {
			return nil, nil, index, err
		}
		sum := sha256.Sum256(b)
		if len(b) != count || hex.EncodeToString(sum[:]) != sha {
			return nil, nil, index, fmt.Errorf("knowledge integrity mismatch for %s", path)
		}
		files[path] = verifiedFile{raw: b}
	}
	for _, path := range append(slices.Clone(policies), recipes) {
		list, idKey := "policies", "policy_id"
		ids := index.PolicyIDs
		if path == recipes {
			list, idKey, ids = "recipes", "recipe_id", index.RecipeIDs
		}
		f := files[path]
		// Other top-level fields need not be arrays.
		var obj map[string]json.RawMessage
		if err := json.Unmarshal(f.raw, &obj); err != nil {
			return nil, nil, index, err
		}

		var rows []json.RawMessage
		if err := json.Unmarshal(obj[list], &rows); err != nil {
			return nil, nil, index, err
		}

		f.records = map[string]knowledgeRecord{}
		for _, r := range rows {
			var c RecordContent
			if err := json.Unmarshal(r, &c); err != nil {
				return nil, nil, index, err
			}
			id, ok := c[idKey].(string)
			_, duplicate := f.records[id]
			if !ok || duplicate {
				return nil, nil, index, errors.New("invalid knowledge record ID")
			}
			f.records[id] = knowledgeRecord{c, r}
			ids[id] = true
		}
		files[path] = f
	}
	for _, path := range evidenceFiles {
		f := files[path]
		if f.raw == nil {
			return nil, nil, index, fmt.Errorf("missing knowledge file %s", path)
		}
		for _, m := range evidenceRow.FindAllSubmatch(f.raw, -1) {
			index.EvidenceIDs[string(m[1])] = true
		}
	}
	return manifest, files, index, nil
}

func sectionText(text, heading string) (string, error) {
	if heading == "*" {
		return strings.Trim(text, "\n"), nil
	}
	lines := strings.Split(text, "\n")
	begin, end, level := -1, len(lines), 0
	for i, line := range lines {
		m := headingLine.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if begin >= 0 && end == len(lines) && len(m[1]) <= level {
			end = i
		}
		if m[2] == heading {
			if begin >= 0 {
				return "", errors.New("duplicate knowledge heading")
			}
			begin, level = i, len(m[1])
		}
	}
	if begin < 0 {
		return "", fmt.Errorf("knowledge section missing: %s", heading)
	}
	return strings.Trim(strings.Join(lines[begin:end], "\n"), "\n"), nil
}

// Python renders recipe excerpts with insertion-ordered keys and a space after
// each comma and colon. Keep the file's token order while decoding its strings.
func recipeText(dec *json.Decoder) (string, error) {
	t, err := dec.Token()
	if err != nil {
		return "", err
	}
	d, ok := t.(json.Delim)
	if !ok {
		b, err := CanonicalJSON(t)
		return string(b), err
	}
	var values []string
	for dec.More() {
		v, err := recipeText(dec)
		if err != nil {
			return "", err
		}
		if d == '{' {
			item, err := recipeText(dec)
			if err != nil {
				return "", err
			}
			v += ": " + item
		}
		values = append(values, v)
	}
	end, err := dec.Token()
	if err != nil {
		return "", err
	}
	return string(d) + strings.Join(values, ", ") + fmt.Sprint(end), nil
}

func policyText(r RecordContent) (string, error) {
	parts := map[string]string{}
	for _, key := range []string{"policy_id", "title", "rationale", "evidence_certainty", "athlete_applicability", "uncertainty"} {
		v, ok := r[key].(string)
		if !ok {
			return "", fmt.Errorf("invalid policy field %s", key)
		}
		parts[key] = v
	}
	for _, key := range []string{"trigger", "suggested_action", "do_not_apply_when", "evidence_ids", "source_ids"} {
		vs, ok := r[key].([]any)
		if !ok {
			return "", fmt.Errorf("invalid policy field %s", key)
		}
		items := make([]string, len(vs))
		for i, v := range vs {
			items[i], ok = v.(string)
			if !ok {
				return "", fmt.Errorf("invalid policy field %s", key)
			}
		}
		sep := "; "
		if key == "evidence_ids" || key == "source_ids" {
			sep = ", "
		}
		parts[key] = strings.Join(items, sep)
	}
	return fmt.Sprintf("%s: %s\nTrigger: %s\nSuggested action: %s\nDo not apply when: %s\nRationale: %s\nEvidence: %s; sources: %s\nCertainty: %s; applicability: %s\nUncertainty: %s", parts["policy_id"], parts["title"], parts["trigger"], parts["suggested_action"], parts["do_not_apply_when"], parts["rationale"], parts["evidence_ids"], parts["source_ids"], parts["evidence_certainty"], parts["athlete_applicability"], parts["uncertainty"]), nil
}

// VerifySelection independently verifies package bytes and reproduces the saved
// section/record selection used to fingerprint a coaching snapshot.
func VerifySelection(root string, selection []SelectionEntry) (VerifiedKnowledge, KnowledgeIndex, error) {
	manifest, files, index, err := knowledgeFiles(root)
	if err != nil {
		return VerifiedKnowledge{}, index, err
	}
	return verifyLoadedSelection(manifest, files, index, selection, nil)
}

func verifyLoadedSelection(manifest map[string]any, files map[string]verifiedFile, index KnowledgeIndex, selection []SelectionEntry, texts map[excerptKey]string) (VerifiedKnowledge, KnowledgeIndex, error) {
	var err error
	excerpts := []any{}
	selected := map[string]SelectedRecord{}
	chars := 0
	for _, item := range selection {
		f, ok := files[item.Path]
		if !ok || f.raw == nil || (item.RecordIDs == nil) == (item.Sections == nil) {
			return VerifiedKnowledge{}, index, errors.New("invalid saved knowledge selection")
		}
		values := item.Sections
		if values == nil {
			values = item.RecordIDs
		}
		if len(values) == 0 {
			return VerifiedKnowledge{}, index, errors.New("empty saved knowledge selection")
		}
		for _, v := range values {
			excerpt := map[string]any{"path": item.Path, "section": nil, "record_id": nil}
			var text string
			if item.Sections != nil {
				if v != "*" {
					excerpt["section"] = v
				}
				text, err = sectionText(string(f.raw), v)
			} else {
				rec, ok := f.records[v]
				if !ok {
					return VerifiedKnowledge{}, index, fmt.Errorf("unknown knowledge record %s", v)
				}
				excerpt["record_id"] = v
				if item.Path == recipes {
					dec := json.NewDecoder(bytes.NewReader(rec.raw))
					dec.UseNumber()
					text, err = recipeText(dec)
				} else {
					text, err = policyText(rec.content)
				}
				selected[item.Path+"\x00"+v] = SelectedRecord{item.Path, v, rec.content}
			}
			if err != nil {
				return VerifiedKnowledge{}, index, err
			}
			chars += utf8.RuneCountInString(text)
			if chars > maxKnowledgeBytes {
				return VerifiedKnowledge{}, index, errors.New("selected knowledge exceeds bound")
			}
			if texts != nil {
				texts[excerptKey{item.Path, v}] = text
			}
			excerpt["text"] = text
			excerpts = append(excerpts, excerpt)
		}
	}
	keys := make([]string, 0, len(selected))
	for k := range selected {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	records := make([]SelectedRecord, 0, len(keys))
	wire := make([]any, 0, len(keys))
	for _, k := range keys {
		r := selected[k]
		records = append(records, r)
		wire = append(wire, map[string]any{"path": r.Path, "record_id": r.RecordID, "content": r.Content})
	}
	b, err := CanonicalJSON(map[string]any{"manifest": manifest, "excerpts": excerpts, "selected_records": wire})
	sum := sha256.Sum256(b)
	return VerifiedKnowledge{Digest: hex.EncodeToString(sum[:]), Selection: selection, SelectedRecords: records}, index, err
}
