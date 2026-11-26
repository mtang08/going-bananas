package metrics

import (
	"testing"

	"github.com/google/uuid"
)

// Expected digests were computed from these inputs by app.metrics.contract.completion_association_hash.
func TestCompletionAssociationHash(t *testing.T) {
	session := uuid.MustParse("00000000-0000-0000-0000-000000000001")
	activity := uuid.MustParse("00000000-0000-0000-0000-000000000002")
	manual := uuid.MustParse("00000000-0000-0000-0000-000000000003")
	reason, note := "schedule", "Café 🍌"
	run := CompletionAssociation{SessionUID: session, ActivityID: &activity, MatchMethod: "explicit", InputVersion: 1}
	revised := run
	revised.InputVersion++
	moved := CompletionAssociation{
		SessionUID: session, ManualSessionID: &manual, MatchMethod: "confirmed_move",
		ModificationReason: &reason, ReasonNote: &note, InputVersion: 2,
	}
	for _, tc := range []struct {
		name string
		link CompletionAssociation
		want string
	}{
		{"linked run", run, "dc45aba5fe2a08a7d9e2f35eebcb36d16c097b99358b0734ab8c838f4cf24581"},
		{"revised link", revised, "f8de153c5da358cf24b7fb5538d9bb6eb38a868888cfd2c302ec2a71c30514e5"},
		{"moved manual session", moved, "5a0e40962bdfe4ebebd5b296600b6d4b2b550e39a0988dcc694a373f36cd1f32"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := tc.link.Hash()
			if err != nil || got != tc.want {
				t.Fatalf("hash = %q, %v; want %q", got, err, tc.want)
			}
		})
	}
}
