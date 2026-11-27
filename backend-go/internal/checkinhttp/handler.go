// Package checkinhttp registers the athlete check-in routes behind the application's local HTTP guards.
package checkinhttp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/internal/checkins"
)

type Handler struct {
	Store checkins.Store
	Mode  string
}

func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("PUT /api/v1/phone/checkins/{entry_id}", h.phone)
	mux.HandleFunc("POST /api/v1/v2/checkins", h.create)
	mux.HandleFunc("PATCH /api/v1/v2/checkins/{checkin_id}", h.patch)
	mux.HandleFunc("GET /api/v1/v2/checkins", h.list)
}

func jsonResponse(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func requestID(w http.ResponseWriter) string {
	if id := w.Header().Get("X-Request-ID"); id != "" {
		return id
	}
	var b [8]byte
	_, _ = rand.Read(b[:])
	id := hex.EncodeToString(b[:])
	w.Header().Set("X-Request-ID", id)
	return id
}
func (h Handler) success(w http.ResponseWriter, status int, data any, rev int32) {
	requestID(w)
	jsonResponse(w, status, map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": rev, "data": data})
}
func problem(w http.ResponseWriter, code int, key, msg string, fields []fieldError) {
	if fields == nil {
		fields = []fieldError{}
	}
	jsonResponse(w, code, map[string]any{"error": map[string]any{"code": key, "message": msg, "fields": fields, "retryable": code >= 500, "request_id": requestID(w)}})
}
func failure(w http.ResponseWriter, err error) {
	var domain *checkins.DomainError
	if errors.As(err, &domain) {
		problem(w, domain.Status, domain.Code, domain.Message, nil)
		return
	}
	problem(w, 500, "internal_error", "Internal server error", nil)
}
func (v *validation) valid(w http.ResponseWriter) bool {
	if len(v.fields) == 0 {
		return true
	}
	problem(w, 422, "validation_error", "Invalid request fields", v.fields)
	return false
}
func (v *validation) id(r *http.Request, key string) uuid.UUID {
	id, err := uuid.Parse(r.PathValue(key))
	if err != nil {
		v.add("path."+key, "Input should be a valid UUID")
	}
	return id
}

const prefix = "phone-first-steps:"

var walkingNotes = map[string]string{"": "First steps: no ankle pain.", "gone": "First-step ankle pain: gone after walking.", "eased": "First-step ankle pain: eased after walking.", "same": "First-step ankle pain: unchanged after walking.", "worse": "First-step ankle pain: worse after walking.", "too_early": "First-step ankle pain: too early to assess walking response."}

func (h Handler) phone(w http.ResponseWriter, r *http.Request) {
	v := new(validation)
	id := v.id(r, "entry_id")
	obj := v.object(r)
	if obj == nil {
		v.valid(w)
		return
	}
	keys := []string{"observed_at", "pain", "walking_response"}
	v.shape(obj, "body", keys, keys)
	input := checkins.Input{IdempotencyKey: prefix + id.String(), Kind: "exception", ContextTags: []string{}, Symptoms: []checkins.Symptom{}}
	if x, ok := obj["observed_at"]; ok {
		input.ObservedAt = v.instant(x, "body.observed_at", true)
	}
	var pain int64
	if x, ok := obj["pain"]; ok {
		n, ok := x.(json.Number)
		a, err := n.Int64()
		pain = a
		switch {
		case !ok || err != nil:
			v.add("body.pain", "Input should be a valid integer")
		case a < 0:
			v.add("body.pain", "Input should be greater than or equal to 0")
		case a > 10:
			v.add("body.pain", "Input should be less than or equal to 10")
		}
	}
	response := ""
	if x := obj["walking_response"]; x != nil {
		response = v.choice(x, "body.walking_response", "gone", "eased", "same", "worse", "too_early")
	}
	if len(v.fields) == 0 && ((pain == 0) != (response == "")) {
		v.add("body", "Value error, A walking response is required exactly when pain is above zero")
	}
	if !v.valid(w) {
		return
	}
	if modes := r.Header.Values("X-Phone-Mode"); len(modes) > 0 && modes[0] != h.Mode {
		problem(w, 409, "phone_mode_mismatch", "The Mac is serving a different workspace", nil)
		return
	}
	reported := pain > 0
	input.PainReported = &reported
	note := walkingNotes[response]
	input.Note = &note
	if reported {
		input.Symptoms = []checkins.Symptom{{Site: "ankle", Side: "na", Severity: float64(pain), Timing: "unknown"}}
	}
	rev, err := h.Store.Phone(r.Context(), input)
	if err != nil {
		failure(w, err)
		return
	}
	h.success(w, 200, map[string]any{"id": id}, rev)
}

type detectedCheckin struct {
	checkins.View
	Exceptions checkins.Detection `json:"exceptions"`
}

func (h Handler) create(w http.ResponseWriter, r *http.Request) {
	v := new(validation)
	obj := v.object(r)
	if obj == nil {
		v.valid(w)
		return
	}
	input, _, _ := v.input(obj, false)
	if !v.valid(w) {
		return
	}
	if strings.HasPrefix(input.IdempotencyKey, prefix) {
		problem(w, 422, "reserved_checkin_key", "Use the morning check-in form for this key", nil)
		return
	}
	row, created, detection, rev, err := h.Store.Create(r.Context(), input)
	if err != nil {
		failure(w, err)
		return
	}
	status := 200
	if created {
		status = 201
	}
	h.success(w, status, detectedCheckin{row, detection}, rev)
}
func (h Handler) patch(w http.ResponseWriter, r *http.Request) {
	v := new(validation)
	id := v.id(r, "checkin_id")
	obj := v.object(r)
	if obj == nil {
		v.valid(w)
		return
	}
	_, expected, changes := v.input(obj, true)
	if !v.valid(w) {
		return
	}
	row, detection, rev, err := h.Store.Patch(r.Context(), id, expected, changes)
	if err != nil {
		failure(w, err)
		return
	}
	h.success(w, 200, detectedCheckin{row, detection}, rev)
}
func (h Handler) list(w http.ResponseWriter, r *http.Request) {
	v := new(validation)
	date := func(key string) *time.Time {
		raw, ok := r.URL.Query()[key]
		if !ok {
			return nil
		}
		d, err := time.Parse(time.DateOnly, raw[len(raw)-1])
		if err != nil {
			v.add("query."+key, "Input should be a valid date or datetime")
		}
		return &d
	}
	start, end := date("start"), date("end")
	if !v.valid(w) {
		return
	}
	rows, rev, err := h.Store.List(r.Context(), start, end)
	if err != nil {
		failure(w, err)
		return
	}
	h.success(w, 200, map[string]any{"items": rows}, rev)
}
