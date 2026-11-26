package httpapi

import (
	"context"
	"net/http"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/planning"
)

type PlanningReader interface {
	Goals(context.Context) (planning.List[db.Goal], error)
	Versions(context.Context, int32) (planning.List[db.ListCalendarVersionsRow], error)
}

func (s server) ListGoals(ctx context.Context, _ api.ListGoalsRequestObject) (api.ListGoalsResponseObject, error) {
	result, err := s.plans.Goals(ctx)
	if err != nil {
		return nil, err
	}
	items := make([]api.Goal, 0, len(result.Items))
	for _, r := range result.Items {
		items = append(items, api.Goal{Id: uuid.UUID(r.ID.Bytes), Text: r.Text, Horizon: api.GoalHorizon(r.Horizon), Priority: int(r.Priority), Status: api.GoalStatus(r.Status), Version: int(r.Version)})
	}
	return api.ListGoals200JSONResponse{SchemaVersion: api.V1, Mode: s.mode, DataRevision: result.DataRevision, Data: api.GoalList{Items: items}}, nil
}

func optional[T any](v T, valid bool) *T {
	if !valid {
		return nil
	}
	return &v
}

func (s server) ListCalendarVersions(ctx context.Context, req api.ListCalendarVersionsRequestObject) (api.ListCalendarVersionsResponseObject, error) {
	limit := 50
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	result, err := s.plans.Versions(ctx, int32(limit))
	if err != nil {
		return nil, err
	}
	items := make([]api.CalendarVersion, 0, len(result.Items))
	for _, r := range result.Items {
		items = append(items, api.CalendarVersion{Id: uuid.UUID(r.ID.Bytes), Number: int(r.Number),
			ParentNumber: optional(int(r.ParentNumber.Int32), r.ParentNumber.Valid),
			Kind:         api.CalendarVersionKind(r.Kind), Actor: api.CalendarVersionActor(r.Actor),
			Reason: optional(r.Reason.String, r.Reason.Valid), ProposalId: optional(uuid.UUID(r.ProposalID.Bytes), r.ProposalID.Valid),
			RestoredFromNumber: optional(int(r.RestoredFromNumber.Int32), r.RestoredFromNumber.Valid),
			BlockVersionId:     optional(uuid.UUID(r.BlockVersionID.Bytes), r.BlockVersionID.Valid),
			CreatedAt:          api.Timestamp(r.CreatedAt.Time.In(time.FixedZone("", int(r.CreatedOffset)))),
		})
	}
	return api.ListCalendarVersions200JSONResponse{SchemaVersion: api.V1, Mode: s.mode, DataRevision: result.DataRevision, Data: api.CalendarVersionList{Items: items}}, nil
}

// FastAPI accepts integral decimal strings and uses the last repeated query value.
func bindCalendarLimit(w http.ResponseWriter, r *http.Request) bool {
	query := r.URL.Query()
	values := query["limit"]
	if len(values) == 0 {
		return true
	}
	limit, message := positiveInteger(values[len(values)-1])
	if limit > 50 {
		message = "Input should be less than or equal to 50"
	}
	if message != "" {
		resp := api.ListCalendarVersions422JSONResponse{Error: api.ValidationErrorDetail{Code: api.ValidationError, Message: "Invalid request fields", Retryable: api.False, RequestId: requestID(r.Context()), Fields: []api.ValidationField{{Field: "query.limit", Message: message}}}}
		_ = resp.VisitListCalendarVersionsResponse(w)
		return false
	}
	query.Set("limit", strconv.Itoa(limit))
	r.URL.RawQuery = query.Encode()
	return true
}
