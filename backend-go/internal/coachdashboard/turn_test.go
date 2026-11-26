package coachdashboard

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func TestTurnReplyLimitInCharacters(t *testing.T) {
	prefix := strings.Repeat("🍌", maxReplyChars-1)
	turn := &runningTurn{}
	if err := turn.addDelta(prefix); err != nil {
		t.Fatal(err)
	}
	if err := turn.addDelta("é🍌"); err != nil {
		t.Fatal(err)
	}
	if err := turn.addDelta("more"); err != nil {
		t.Fatal(err)
	}
	want := prefix + "é"
	if turn.partial.String() != want {
		t.Fatal("streamed reply exceeded character limit")
	}
	reply, problem := turnResult(want+"🍌", nil)
	if problem != nil || reply != want {
		t.Fatal("final reply exceeded character limit")
	}
}

func TestTurnFailuresKeepPrivateTransportDetailsOutOfReview(t *testing.T) {
	for _, tc := range []struct {
		reply string
		err   error
		code  string
	}{
		{" \t", nil, "turn_failed"},
		{"partial", errors.New("private app-server details"), "turn_failed"},
		{"partial", context.Canceled, "interrupted"},
		{"", fmt.Errorf("runtime: %w", &Problem{Code: "auth_required", Message: "Sign in to continue."}), "auth_required"},
	} {
		reply, problem := turnResult(tc.reply, tc.err)
		if reply != "" || problem == nil || problem.Code != tc.code || strings.Contains(problem.Message, "private") {
			t.Fatalf("unexpected failure result %q %#v", reply, problem)
		}
	}
}
