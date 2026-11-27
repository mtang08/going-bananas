package garmincli

import (
	"context"
	"sync"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
)

// Open the credential-backed client inside a claimed job so token service outages
// go through the same durable retry and coverage transitions as a data request.
type clientSource struct {
	cfg    garmin.Config
	mu     sync.Mutex
	client *garmin.Client
}

func (s *clientSource) open(ctx context.Context) (*garmin.Client, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.client != nil {
		return s.client, nil
	}
	client, err := garmin.Open(ctx, s.cfg)
	if err == nil {
		s.client = client
	}
	return client, err
}
func (s *clientSource) SearchPage(ctx context.Context, offset, limit int, first, last time.Time) ([]garmin.Record, error) {
	c, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	return c.SearchPage(ctx, offset, limit, first, last)
}
func (s *clientSource) FetchRecovery(ctx context.Context, dataset string, first, last time.Time) ([]garmin.Record, error) {
	c, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	return c.FetchRecovery(ctx, dataset, first, last)
}
func (s *clientSource) DownloadActivity(ctx context.Context, id string) ([]byte, error) {
	c, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	return c.DownloadActivity(ctx, id)
}
