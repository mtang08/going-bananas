package httpapi

import (
	"context"
	"time"

	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
)

type ProposalReader interface {
	List(context.Context, string) (proposals.List, error)
}

type server struct {
	plans  PlanningReader
	reader ProposalReader
	writer GoalWriter
	mode   api.AppMode
}

func timestamp(v *time.Time) *api.Timestamp { return (*api.Timestamp)(v) }

func (s server) GetProposalsApiV1CoachProposalsGet(ctx context.Context, req api.GetProposalsApiV1CoachProposalsGetRequestObject) (api.GetProposalsApiV1CoachProposalsGetResponseObject, error) {
	filter := ""
	if v := req.Params.Status; v != nil {
		if !v.Valid() {
			return api.GetProposalsApiV1CoachProposalsGet422JSONResponse{Error: api.ValidationErrorDetail{
				Code:      api.ValidationError,
				Message:   "Invalid request fields",
				Retryable: api.False,
				RequestId: requestID(ctx),
				Fields: []api.ValidationField{{
					Field:   "query.status",
					Message: "Input should be 'open', 'pending', 'accepted', 'partially_accepted', 'rejected', 'stale', 'invalid' or 'discarded'",
				}},
			}}, nil
		}
		filter = string(*v)
	}
	result, err := s.reader.List(ctx, filter)
	if err != nil {
		return nil, err
	}
	items := make([]api.ProposalSummary, 0, len(result.Items))
	for _, row := range result.Items {
		items = append(items, api.ProposalSummary{
			Id:                  row.ID,
			Revision:            row.Revision,
			Operation:           row.Operation,
			Status:              api.ProposalSummaryStatus(row.Status),
			SubmittedAt:         api.Timestamp(row.SubmittedAt),
			DecidedAt:           timestamp(row.DecidedAt),
			DiscardedAt:         timestamp(row.DiscardedAt),
			Headline:            row.Headline,
			BaseCalendarVersion: row.BaseCalendarVersion,
			ChangeCount:         row.ChangeCount,
		})
	}
	return api.GetProposalsApiV1CoachProposalsGet200JSONResponse{
		Data:          api.ProposalList{Items: items},
		DataRevision:  result.DataRevision,
		SchemaVersion: api.V1,
		Mode:          s.mode,
	}, nil
}
