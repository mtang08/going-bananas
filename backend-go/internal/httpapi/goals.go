package httpapi

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/goals"
	"github.com/oapi-codegen/nullable"
)

type GoalWriter interface {
	Patch(context.Context, uuid.UUID, goals.Patch) (goals.Result, error)
}

func suppliedValue[T any](field nullable.Nullable[T]) *T {
	v, err := field.Get()
	if err != nil {
		return nil
	}
	return &v
}

func (s server) PatchGoal(ctx context.Context, req api.PatchGoalRequestObject) (api.PatchGoalResponseObject, error) {
	body := req.Body
	result, err := s.writer.Patch(ctx, req.GoalId, goals.Patch{
		ExpectedVersion: body.ExpectedVersion,
		Text:            suppliedValue(body.Text),
		Priority:        suppliedValue(body.Priority),
		Horizon:         (*string)(suppliedValue(body.Horizon)),
		Status:          (*string)(suppliedValue(body.Status)),
		HasNull:         body.Text.IsNull() || body.Priority.IsNull() || body.Horizon.IsNull() || body.Status.IsNull(),
	})
	makeError := func(code, message string) api.ErrorEnvelope {
		return api.ErrorEnvelope{Error: api.ErrorDetail{Code: code, Message: message, RequestId: requestID(ctx), Fields: []api.ValidationField{}}}
	}
	switch {
	case errors.Is(err, goals.ErrNotFound):
		return api.PatchGoal404JSONResponse(makeError("goal_not_found", "Goal not found")), nil
	case errors.Is(err, goals.ErrVersionConflict):
		return api.PatchGoal409JSONResponse(makeError("version_conflict", "Goal changed; reload before editing")), nil
	case errors.Is(err, goals.ErrNullField):
		return api.PatchGoal422JSONResponse(makeError("invalid_goal", "Goal fields cannot be null")), nil
	case err != nil:
		return nil, err
	}
	row := result.Goal
	return api.PatchGoal200JSONResponse{
		SchemaVersion: api.V1,
		Mode:          s.mode,
		DataRevision:  result.DataRevision,
		Data: api.Goal{
			Id:       row.ID,
			Text:     row.Text,
			Horizon:  api.GoalHorizon(row.Horizon),
			Priority: row.Priority,
			Status:   api.GoalStatus(row.Status),
			Version:  row.Version,
		},
	}, nil
}

func (s server) serveGoal(w http.ResponseWriter, r *http.Request, rawID string) {
	id, idErr := uuid.Parse(rawID)
	input, fields := decodeGoalPatch(r.Body)
	invalidWrapper := len(rawID) == 38 && (!strings.HasPrefix(rawID, "{") || !strings.HasSuffix(rawID, "}")) || len(rawID) == 45 && !strings.HasPrefix(rawID, "urn:uuid:")
	if (idErr != nil || invalidWrapper) && (len(fields) == 0 || fields[0].Message != "JSON decode error") {
		fields = append([]api.ValidationField{{Field: "path.goal_id", Message: uuidMessage(rawID)}}, fields...)
	}
	if len(fields) > 0 {
		resp := api.PatchGoal422JSONResponse{Error: api.ErrorDetail{Code: "validation_error", Message: "Invalid request fields", RequestId: requestID(r.Context()), Fields: fields}}
		_ = resp.VisitPatchGoalResponse(w)
		return
	}
	response, err := s.PatchGoal(r.Context(), api.PatchGoalRequestObject{GoalId: id, Body: &input})
	if err != nil {
		internalError(w, r, err)
		return
	}
	if err := response.VisitPatchGoalResponse(w); err != nil {
		internalError(w, r, err)
	}
}
