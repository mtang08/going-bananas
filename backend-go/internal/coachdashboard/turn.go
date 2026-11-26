// Package coachdashboard manages the athlete's dashboard review conversation.
package coachdashboard

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

const maxReplyChars = 60_000

// AppServer executes one user-initiated message. Implementations must stop on
// context cancellation and finish all callbacks before returning.
type AppServer interface {
	RunTurn(context.Context, TurnRequest) (string, error)
}

type TurnRequest struct {
 TurnID string
	ThreadID string
	Message  string
	OnThread func(string) error
	OnDelta  func(string) error
}

type runningTurn struct {
	id, responseID string
	cancel         context.CancelFunc
	done           chan struct{}
	mu             sync.Mutex
	partial        strings.Builder
	chars          int
}

func (t *runningTurn) addDelta(value string) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	value, n := limitText(value, maxReplyChars-t.chars)
	t.partial.WriteString(value)
	t.chars += n
	return nil
}

func limitText(value string, maxChars int) (string, int) {
	n := 0
	for i := range value {
		if n == maxChars {
			return value[:i], n
		}
		n++
	}
	return value, n
}

type Gateway struct {
	store     *Store
	transport AppServer
	mu        sync.Mutex
	turn      *runningTurn
	closed    bool
}

func NewGateway(store *Store, transport AppServer) *Gateway {
	return &Gateway{store: store, transport: transport}
}

// View contains the athlete-facing chat state. Runtime IDs stay in the store.
type View struct {
	ID               *string   `json:"id"`
	Status           string    `json:"status"`
	Messages         []Message `json:"messages"`
	Error            *Problem  `json:"error"`
	ProposalID       *string   `json:"proposal_id"`
	ProposalRevision *int      `json:"proposal_revision"`
}

func (g *Gateway) View(ctx context.Context) (View, error) {
	review, err := g.store.Review(ctx)
	if err != nil {
		return View{}, err
	}
	g.mu.Lock()
	t := g.turn
	g.mu.Unlock()
	if t != nil && t.id == review.ActiveTurn {
		t.mu.Lock()
		if t.chars > 0 {
			review.Messages = append(review.Messages, Message{ID: t.responseID, Role: "assistant", Text: t.partial.String()})
		}
		t.mu.Unlock()
	}
	view := View{Status: review.Status, Messages: review.Messages, Error: review.Error}
	if review.ID != "" {
		view.ID = &review.ID
	}
	if review.ProposalID != "" {
		view.ProposalID = &review.ProposalID
	}
	return view, nil
}

func (g *Gateway) Send(ctx context.Context, guard Guard, clientID, text, intent string) error {
	parsed, err := uuid.Parse(clientID)
	if err != nil {
		return &Problem{Code: "invalid_message", Message: "A valid client message ID is required."}
	}
	clientID = parsed.String()
	text = strings.TrimSpace(text)
	if text == "" || utf8.RuneCountInString(text) > 8000 {
		return &Problem{Code: "invalid_message", Message: "Enter a message between 1 and 8000 characters."}
	}
	message := text
	switch intent {
	case "":
	case "sunday_review":
		message = "The athlete selected Sunday Review.\n\n" + text
	case "today_run":
		message = "The athlete selected Review Today's Run.\n\n" + text
	default:
		return &Problem{Code: "invalid_message", Message: "Choose a supported coaching intent."}
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed {
		return errors.New("dashboard gateway is shut down")
	}
	lease, err := g.store.Enqueue(ctx, guard, clientID, text, intent)
	if err != nil || lease == nil {
		return err
	}
	turnCtx, cancel := context.WithCancel(context.Background())
	t := &runningTurn{id: lease.ID, responseID: uuid.NewString(), done: make(chan struct{}), cancel: cancel}
	g.turn = t
	go g.run(turnCtx, t, lease, message)
	return nil
}

func (g *Gateway) run(ctx context.Context, t *runningTurn, lease *TurnLease, message string) {
	defer func() {
		t.cancel()
		lease.Close()
		g.mu.Lock()
		if g.turn == t {
			g.turn = nil
		}
		close(t.done)
		g.mu.Unlock()
	}()
	active, err := g.store.IsActive(ctx, t.id)
	var reply string
	if err == nil && active {
		watchDone := make(chan struct{})
		go func() {
			defer close(watchDone)
			g.watchCancellation(ctx, t)
		}()
		req := TurnRequest{TurnID:t.id, ThreadID: lease.ThreadID, Message: message, OnDelta: t.addDelta, OnThread: func(thread string) error {
			return g.store.SaveThread(ctx, t.id, thread)
		}}
		reply, err = g.transport.RunTurn(ctx, req)
		if ctx.Err() != nil {
			err = ctx.Err()
		}
		t.cancel()
		<-watchDone
	} else if err == nil {
		return
	}
	reply, problem := turnResult(reply, err)
	finishCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := g.store.Finish(finishCtx, t.id, t.responseID, reply, problem); err != nil {
		slog.Error("could not persist dashboard turn completion")
	}
}

func turnResult(reply string, err error) (string, *Problem) {
	if errors.Is(err, context.Canceled) {
		return "", &Problem{Code: "interrupted", Message: "The coach stopped before finishing. Try again."}
	}
	if err != nil {
		var problem *Problem
		if errors.As(err, &problem) {
			return "", problem
		}
		return "", &Problem{Code: "turn_failed", Message: "The coach could not finish this request. Try again."}
	}
	reply, _ = limitText(reply, maxReplyChars)
	if strings.TrimSpace(reply) == "" {
		return "", &Problem{Code: "turn_failed", Message: "The coach returned an empty reply. Try again."}
	}
	return reply, nil
}

func (g *Gateway) watchCancellation(ctx context.Context, t *runningTurn) {
	ticker := time.NewTicker(350 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			active, err := g.store.IsActive(ctx, t.id)
			if err != nil || !active {
				t.cancel()
				return
			}
		}
	}
}

func (g *Gateway) Cancel(ctx context.Context, guard Guard) error {
	id, err := g.store.Cancel(ctx, guard)
	if err != nil {
		return err
	}
	g.mu.Lock()
	t := g.turn
	g.mu.Unlock()
	if t != nil && t.id == id {
		return stopTurn(ctx, t)
	}
	return nil
}

func (g *Gateway) New(ctx context.Context, guard Guard) error {
	return g.store.NewReview(ctx, guard)
}

func (g *Gateway) Shutdown(ctx context.Context) error {
	g.mu.Lock()
	g.closed = true
	t := g.turn
	g.mu.Unlock()
	if t != nil {
		return stopTurn(ctx, t)
	}
	return nil
}

func stopTurn(ctx context.Context, t *runningTurn) error {
	t.cancel()
	select {
	case <-t.done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
