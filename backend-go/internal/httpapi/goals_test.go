package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/goals"
)

type patchFunc func(context.Context, uuid.UUID, goals.Patch) (goals.Result, error)

func (f patchFunc) Patch(ctx context.Context, id uuid.UUID, p goals.Patch) (goals.Result, error) {
	return f(ctx, id, p)
}

func TestGoalPatchHTTP(t *testing.T) {
	const id = "9248048b-7c1e-4948-b0a1-f0623c9d7e13"
	writer := patchFunc(func(_ context.Context, key uuid.UUID, p goals.Patch) (goals.Result, error) {
		if key.String() != id {
			return goals.Result{}, goals.ErrNotFound
		}
		if p.ExpectedVersion != 1 {
			return goals.Result{}, goals.ErrVersionConflict
		}
		if p.HasNull {
			return goals.Result{}, goals.ErrNullField
		}
		row := goals.Goal{ID: key, Text: "existing goal", Priority: 1, Status: "active", Horizon: "season", Version: 2}
		if p.Text != nil {
			row.Text = *p.Text
		}
		if p.Priority != nil {
			row.Priority = *p.Priority
		}
		if p.Status != nil {
			row.Status = *p.Status
		}
		if p.Horizon != nil {
			row.Horizon = *p.Horizon
		}
		if row.Text == "fail" {
			return goals.Result{}, errors.New("private DB failure")
		}
		return goals.Result{Goal: row, DataRevision: 17}, nil
	})
	ts := httptest.NewUnstartedServer(nil)
	_, port, _ := strings.Cut(ts.Listener.Addr().String(), ":")
	ts.Config.Handler = New(nil, writer, api.Test, port, "5173")
	ts.Start()
	defer ts.Close()
	request := func(id, body, local, contentType, origin string) (int, []byte, http.Header) {
		t.Helper()
		req, err := http.NewRequest(http.MethodPatch, ts.URL+"/api/v1/goals/"+id, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Origin", origin)
		req.Header.Set("X-Local-Request", local)
		req.Header.Set("Content-Type", contentType)
		resp, err := ts.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = resp.Body.Close() }()
		b, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		return resp.StatusCode, b, resp.Header
	}
	for _, tc := range []struct {
		id, body, code string
		status         int
		fields         []string
	}{
		{id, `{"expected_version":"1.00","status":"paused","horizon":"long_term","priority":2.0,"text":"  Fall race  "}`, "", 200, nil},
		{id, `{"expected_version":true}`, "", 200, nil},
		{id, `{"expected_version":2,"status":null}`, "version_conflict", 409, nil},
		{uuid.Nil.String(), `{"expected_version":1,"status":null}`, "goal_not_found", 404, nil},
		{id, `{"expected_version":1,"text":null}`, "invalid_goal", 422, nil},
		{id, `{"extra2":0,"horizon":"week","priority":0,"text":"  ","status":"foo","extra1":null}`, "validation_error", 422, []string{"body.expected_version", "body.text", "body.horizon", "body.priority", "body.status", "body.extra2", "body.extra1"}},
		{"not-a-uuid", `{"expected_version":{}}`, "validation_error", 422, []string{"path.goal_id", "body.expected_version"}},
		{id, "", "validation_error", 422, []string{"body"}},
		{id, "[]", "validation_error", 422, []string{"body"}},
		{id, `{"text":}`, "validation_error", 422, []string{"body.8"}},
		{id, `{"expected_version":1,"text":"fail"}`, "internal_error", 500, nil},
	} {
		status, b, headers := request(tc.id, tc.body, "1", "application/json", "http://127.0.0.1:5173")
		if status != tc.status {
			t.Errorf("%s: %d %s", tc.body, status, b)
			continue
		}
		if status == 200 {
			var data api.GoalEnvelope
			if err := json.Unmarshal(b, &data); err != nil {
				t.Fatal(err)
			}
			if data.Data.Id.String() != id || data.Mode != api.Test || data.DataRevision != 17 || data.Data.Version != 2 {
				t.Fatalf("bad success: %s", b)
			}
			if strings.Contains(tc.body, "Fall race") && (data.Data.Text != "Fall race" || data.Data.Priority != 2 || data.Data.Status != api.Paused || data.Data.Horizon != api.LongTerm) {
				t.Errorf("patch lost fields: %s", b)
			}
			continue
		}
		var e api.ErrorEnvelope
		if err := json.Unmarshal(b, &e); err != nil {
			t.Fatal(err)
		}
		if e.Error.Code != tc.code || e.Error.Retryable != (status == 500) || e.Error.Fields == nil || e.Error.RequestId == "" {
			t.Errorf("bad error: %s", b)
		}
		if status != 500 && e.Error.RequestId != headers.Get("X-Request-ID") {
			t.Error("request ID mismatch")
		}
		if len(e.Error.Fields) != len(tc.fields) {
			t.Fatalf("field count: %s", b)
		}
		for i, field := range tc.fields {
			if e.Error.Fields[i].Field != field {
				t.Errorf("field[%s]=%s", strconv.Itoa(i), b)
			}
		}
	}
	for _, tc := range []struct {
		local, ct, origin string
		status            int
	}{
		{"", "application/json", "", 403}, {"1", "text/plain", "", 415}, {"1", "application/json", "http://foreign.example", 403},
	} {
		status, _, _ := request(id, `{"expected_version":1}`, tc.local, tc.ct, tc.origin)
		if status != tc.status {
			t.Errorf("guard returned %d", status)
		}
	}
}
