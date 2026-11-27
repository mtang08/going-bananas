// Package proposalhttp exposes manual draft review and decision routes on the
// local, synthetic API's guarded HTTP mux.
package proposalhttp

import (
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Handler struct {
	Store        drafts.Store
	KBRoot, Mode string
	Now          func() time.Time
}

const prefix = "/api/v1/coach/proposals"

func (h Handler) Register(mux *http.ServeMux) {
	if h.Mode != "demo" && h.Mode != "test" && h.Mode != "real" {
		return
	}
	routes := map[string]string{
		"GET " + prefix + "/active":                    "active",
		"GET " + prefix + "/{id}":                      "detail",
		"GET " + prefix + "/{id}/document":             "document",
		"GET " + prefix + "/{id}/revisions/{revision}": "revision",
		"DELETE " + prefix + "/{id}":                   "discard",
		"POST " + prefix + "/{id}/revise":              "revise",
	}
	routes["POST "+prefix+"/{id}/decision"] = "decide"
	for pattern, method := range routes {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) { h.serve(w, r, method) })
	}
}

type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func problem(w http.ResponseWriter, status int, code, msg string, fields any) {
	writeJSON(w, status, map[string]any{"error": map[string]any{"code": code, "message": msg, "retryable": status >= 500, "fields": fields, "request_id": w.Header().Get("X-Request-ID")}})
}
func invalid(w http.ResponseWriter, fields []field) {
	problem(w, 422, "validation_error", "Invalid request fields", fields)
}
func writeError(w http.ResponseWriter, err error) {
	var domain *drafts.Error
	var command *drafts.CommandError
	if errors.As(err, &domain) {
		var fields any = []field{}
		if errors.As(err, &command) && len(command.Issues) > 0 {
			fields = command.Issues
		}
		problem(w, domain.Status, domain.Code, domain.Message, fields)
		return
	}
	problem(w, 500, "internal_error", "Internal server error", []field{})
}
func bindBody(r *http.Request) (json.RawMessage, []field) {
	b, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, []field{{"body", "JSON decode error"}}
	}
	if len(b) == 0 || string(b) == "null" {
		return nil, []field{{"body", "Field required"}}
	}
	if !json.Valid(b) {
		var raw json.RawMessage
		err := json.Unmarshal(b, &raw)
		var se *json.SyntaxError
		pos := 0
		if errors.As(err, &se) {
			pos = int(se.Offset)
			if pos < len(b) {
				pos--
			}
		}
		return nil, []field{{"body." + strconv.Itoa(pos), "JSON decode error"}}
	}
	return b, nil
}
func issues(in []drafts.Issue) []field {
	out := make([]field, 0, len(in))
	for _, item := range in {
		out = append(out, field{item.Path, item.Message})
	}
	return out
}
func (h Handler) serve(w http.ResponseWriter, r *http.Request, method string) {
	ctx := r.Context()
	now := time.Now().UTC()
	if h.Now != nil {
		now = h.Now()
	}
	id := uuid.Nil
	if v := r.PathValue("id"); v != "" {
		var err error
		id, err = uuid.Parse(v)
		if err != nil {
			invalid(w, []field{{"path.proposal_id", "Input should be a valid UUID"}})
			return
		}
	}
	var body json.RawMessage
	if r.Method == "POST" {
		var fields []field
		body, fields = bindBody(r)
		if len(fields) > 0 {
			invalid(w, fields)
			return
		}
	}
	var data any
	var err error
	revision := -1
	switch method {
	case "active":
		list, e := proposals.New(h.Store.Pool).List(ctx, "open")
		err = e
		revision = int(list.DataRevision)
		var active any
		if len(list.Items) > 0 {
			row := list.Items[0]
			active = api.ProposalSummary{Id: row.ID, Revision: row.Revision, Operation: row.Operation, Status: api.ProposalSummaryStatus(row.Status), SubmittedAt: api.Timestamp(row.SubmittedAt), DecidedAt: (*api.Timestamp)(row.DecidedAt), DiscardedAt: (*api.Timestamp)(row.DiscardedAt), Headline: row.Headline, BaseCalendarVersion: row.BaseCalendarVersion, ChangeCount: row.ChangeCount}
		}
		data = map[string]any{"proposal": active}
	case "detail", "document", "revision":
		n := 0
		if method == "revision" {
			n, err = strconv.Atoi(r.PathValue("revision"))
			if err != nil {
				invalid(w, []field{{"path.revision", "Input should be a valid integer, unable to parse string as an integer"}})
				return
			}
		}
		var view drafts.View
		view, err = h.Store.ReadProposal(ctx, id, method, n, now, h.KBRoot)
		data, revision = view.Data, view.Revision
	case "discard":
		values := r.URL.Query()["expected_revision"]
		if len(values) == 0 {
			invalid(w, []field{{"query.expected_revision", "Field required"}})
			return
		}
		n, e := strconv.Atoi(strings.TrimSpace(values[len(values)-1]))
		if e != nil {
			invalid(w, []field{{"query.expected_revision", "Input should be a valid integer, unable to parse string as an integer"}})
			return
		}
		if n <= 0 {
			invalid(w, []field{{"query.expected_revision", "Input should be greater than 0"}})
			return
		}
		data, err = h.Store.Discard(ctx, id, n, now)
	case "revise":
		req, fields, e := drafts.ParseRevisionRequest(body)
		if e != nil {
			writeError(w, e)
			return
		}
		if len(fields) > 0 {
			invalid(w, issues(fields))
			return
		}
		var result drafts.EditResult
		result, err = h.Store.Revise(ctx, id, req, now, drafts.NewValidator(h.KBRoot))
		data = struct {
			drafts.Receipt
			Errors []drafts.Issue `json:"errors"`
		}{result.Receipt, result.Issues}
	case "decide":
		req, fields, e := drafts.ParseDecisionRequest(body)
		if e != nil {
			writeError(w, e)
			return
		}
		if len(fields) > 0 {
			invalid(w, issues(fields))
			return
		}
		data, err = h.Store.Decide(ctx, id, req, now, h.KBRoot, refresh.PlanMetrics(now, refresh.Runs))
	}
	if err == nil && revision < 0 {
		revision, err = h.Store.DataRevision(ctx)
	}
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": revision, "data": data})
}
