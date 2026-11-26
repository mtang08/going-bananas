// Package coachdashboard persists the local athlete's dashboard conversation.
package coachdashboard

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

type Problem struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func (p *Problem) Error() string { return p.Message }

type Message struct {
	ID              string  `json:"id"`
	Role            string  `json:"role"`
	Text            string  `json:"text"`
	ClientMessageID *string `json:"client_message_id"`
}

type Review struct {
	ID                 string    `json:"id"`
	Status             string    `json:"status"`
	Messages           []Message `json:"messages"`
	Error              *Problem  `json:"error"`
	ProposalID         string    `json:"proposal_id,omitempty"`
	ThreadID           string    `json:"codex_thread_id,omitempty"`
	ActiveTurn         string    `json:"active_turn,omitempty"`
	SnapshotIDs        []string  `json:"snapshot_ids,omitempty"`
	ReadActiveProposal bool      `json:"read_active_proposal,omitempty"`
	ObservedProposal   string    `json:"observed_proposal,omitempty"`
	ObservedRevision   int       `json:"observed_revision,omitempty"`
	ProposalRevision   int       `json:"proposal_revision,omitempty"`
}

// Guard distinguishes a missing thread_id from an explicit null (ID == "").
type Guard struct {
	Set bool
	ID  string
}

func (g Guard) check(r Review) error {
	if g.Set && g.ID != r.ID {
		return &Problem{"chat_review_changed", "The coaching review changed. Refresh it before trying again."}
	}
	return nil
}

type Store struct {
	pool *pgxpool.Pool
	mode string
}

func NewStore(pool *pgxpool.Pool, mode string) *Store { return &Store{pool: pool, mode: mode} }

func idleReview(id string) Review {
	return Review{ID: id, Status: "idle", Messages: []Message{}}
}

// Use distinct advisory lock namespaces for atomic state transitions and the
// lifetime of a model turn. PostgreSQL releases both when their owner exits.
const stateLock = "SELECT pg_advisory_xact_lock('coach_chat_reviews'::regclass::int, hashtext($1))"
const tryTurnLock = "SELECT pg_try_advisory_lock('coach_chat_receipts'::regclass::int, hashtext($1))"
const probeTurnLock = "SELECT pg_try_advisory_xact_lock('coach_chat_receipts'::regclass::int, hashtext($1))"

func (s *Store) load(ctx context.Context, tx pgx.Tx) (Review, error) {
	if _, err := tx.Exec(ctx, stateLock, s.mode); err != nil {
		return Review{}, err
	}
	var r Review
	err := tx.QueryRow(ctx, "SELECT state FROM coach_chat_reviews WHERE mode=$1 AND current", s.mode).Scan(&r)
	if errors.Is(err, pgx.ErrNoRows) {
		return idleReview(""), nil
	}
	if err != nil || r.Status != "running" {
		return r, err
	}
	var abandoned bool
	if err := tx.QueryRow(ctx, probeTurnLock, s.mode).Scan(&abandoned); err != nil {
		return Review{}, err
	}
	if abandoned {
		r.ActiveTurn = ""
		r.Status = "failed"
		r.Error = &Problem{"interrupted", "The coach stopped before finishing. Try again."}
		if err := s.save(ctx, tx, r); err != nil {
			return Review{}, err
		}
	}
	return r, nil
}

func (s *Store) save(ctx context.Context, tx pgx.Tx, r Review) error {
	_, err := tx.Exec(ctx, `INSERT INTO coach_chat_reviews (mode,id,state,current) VALUES ($1,$2,$3,true)
		ON CONFLICT (mode,id) DO UPDATE SET state=excluded.state`, s.mode, r.ID, r)
	return err
}

func (s *Store) withReview(ctx context.Context, f func(pgx.Tx, Review) error) error {
	return pgx.BeginFunc(ctx, s.pool, func(tx pgx.Tx) error {
		r, err := s.load(ctx, tx)
		if err != nil {
			return err
		}
		return f(tx, r)
	})
}

func (s *Store) Review(ctx context.Context) (r Review, err error) {
	err = s.withReview(ctx, func(_ pgx.Tx, current Review) error { r = current; return nil })
	return
}

func (s *Store) NewReview(ctx context.Context, g Guard) error {
	return s.withReview(ctx, func(tx pgx.Tx, r Review) error {
		if err := g.check(r); err != nil {
			return err
		}
		if r.Status == "running" {
			return &Problem{"chat_running", "Stop the current turn before starting a new review."}
		}
		if r.ID != "" {
			sql := "UPDATE coach_chat_reviews SET current=false WHERE mode=$1 AND current"
			if len(r.Messages) == 0 {
				sql = "DELETE FROM coach_chat_reviews WHERE mode=$1 AND current"
			}
			if _, err := tx.Exec(ctx, sql, s.mode); err != nil {
				return err
			}
		}
		return s.save(ctx, tx, idleReview(uuid.NewString()))
	})
}

type TurnLease struct {
	ID, ThreadID string
	conn         *pgx.Conn
	once         sync.Once
}

func (l *TurnLease) Close() {
	l.once.Do(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = l.conn.Close(ctx)
	})
}

func receiptDigest(text, intent string) (string, error) {
	payload := map[string]any{"text": text, "intent": nil}
	if intent != "" {
		payload["intent"] = intent
	}
	data, err := coaching.CanonicalJSON(payload)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

func (s *Store) Enqueue(ctx context.Context, g Guard, clientID, text, intent string) (*TurnLease, error) {
	text = strings.TrimSpace(text)
	digest, err := receiptDigest(text, intent)
	if err != nil {
		return nil, err
	}
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return nil, err
	}
	// A session lock must never be returned to the pool. Detaching also leaves
	// pool capacity for cancellation and polling during a long-running turn.
	lease := &TurnLease{ID: uuid.NewString(), conn: conn.Hijack()}
	replay := false
	err = pgx.BeginFunc(ctx, lease.conn, func(tx pgx.Tx) error {
		r, err := s.load(ctx, tx)
		if err != nil {
			return err
		}
		var previous string
		err = tx.QueryRow(ctx, "SELECT digest FROM coach_chat_receipts WHERE mode=$1 AND client_message_id=$2", s.mode, clientID).Scan(&previous)
		switch {
		case err == nil:
			if previous != digest {
				return &Problem{"chat_message_conflict", "This message ID was already used for a different message."}
			}
			replay = true
			return nil
		case !errors.Is(err, pgx.ErrNoRows):
			return err
		}
		if err := g.check(r); err != nil {
			return err
		}
		var granted bool
		if err := tx.QueryRow(ctx, tryTurnLock, s.mode).Scan(&granted); err != nil {
			return err
		}
		if !granted {
			return &Problem{"chat_running", "The coach is still finishing a turn. Wait or stop the turn first."}
		}
		if r.ID == "" {
			r.ID = uuid.NewString()
		}
		lease.ThreadID = r.ThreadID
		r.Status = "running"
		r.ActiveTurn = lease.ID
		r.Error = nil
		r.Messages = append(r.Messages, Message{ID: lease.ID, Role: "user", Text: text, ClientMessageID: &clientID})
		if err := s.save(ctx, tx, r); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, "INSERT INTO coach_chat_receipts (mode,client_message_id,digest) VALUES ($1,$2,$3)", s.mode, clientID, digest)
		return err
	})
	if err != nil || replay {
		lease.Close()
		return nil, err
	}
	return lease, nil
}

func (s *Store) Cancel(ctx context.Context, g Guard) (string, error) {
	var turn string
	err := s.withReview(ctx, func(tx pgx.Tx, r Review) error {
		if err := g.check(r); err != nil {
			return err
		}
		turn = r.ActiveTurn
		if turn == "" {
			return nil
		}
		r.Status = "cancelled"
		r.ActiveTurn = ""
		r.Error = nil
		return s.save(ctx, tx, r)
	})
	return turn, err
}

func (s *Store) updateTurn(ctx context.Context, id string, update func(*Review)) error {
	return s.withReview(ctx, func(tx pgx.Tx, r Review) error {
		if id == "" || r.ActiveTurn != id {
			return nil
		}
		update(&r)
		return s.save(ctx, tx, r)
	})
}

func (s *Store) SaveThread(ctx context.Context, turnID, threadID string) error {
	return s.updateTurn(ctx, turnID, func(r *Review) { r.ThreadID = threadID })
}

func (s *Store) Finish(ctx context.Context, turnID, responseID, reply string, problem *Problem) error {
	return s.updateTurn(ctx, turnID, func(r *Review) {
		r.ActiveTurn = ""
		if problem != nil || strings.TrimSpace(reply) == "" {
			r.Status = "failed"
			if problem == nil {
				problem = &Problem{"turn_failed", "The coach returned an empty reply. Try again."}
			}
			r.Error = problem
			return
		}
		r.Status = "idle"
		r.Error = nil
		r.Messages = append(r.Messages, Message{ID: responseID, Role: "assistant", Text: reply})
	})
}

// IsActive lets another gateway cancel a turn without copying its transcript.
func (s *Store) IsActive(ctx context.Context, turnID string) (bool, error) {
	var active bool
	err := s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM coach_chat_reviews
		WHERE mode=$1 AND current AND state->>'status'='running' AND state->>'active_turn'=$2)`, s.mode, turnID).Scan(&active)
	return active, err
}
