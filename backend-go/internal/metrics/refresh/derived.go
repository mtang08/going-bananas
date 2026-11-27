package refresh

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/matching/rematch"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/trainingwindows"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
	"maps"
	"slices"
	"time"
)

// DerivedScopes rematches sources, refreshes metrics and regenerates prompts after a source write in the same transaction.
func DerivedScopes(ctx context.Context, tx pgx.Tx, scopes []string, now time.Time) error {
	if len(scopes) == 0 || !slices.ContainsFunc(scopes, func(s string) bool { return s != "revision" }) {
		return nil
	}
	b, err := newBatch(ctx, tx, now, nil)
	if err != nil {
		return err
	}
	s, err := b.expand(scopes)
	if err != nil {
		return err
	}
	other := b.broad || s.since != "" || len(s.dates)+len(s.plans)+len(s.strength)+len(b.explicit) > 0
	recoveryOnly := len(s.recovery) > 0 && !other && len(s.manual) == 0
	today := now.In(b.zone).Format(time.DateOnly)
	includeToday := false
	if recoveryOnly {
		complete, err := trainingwindows.Complete(ctx, tx, today)
		if err != nil {
			return err
		}
		includeToday = !complete
	}
	manualOnly := len(s.manual) > 0 && !other && len(s.recovery) == 0
	began := map[string]bool{}
	var matched []uuid.UUID
	if manualOnly {
		days, err := b.dateRows(`SELECT DISTINCT local_date::text FROM (SELECT DISTINCT ON(session_uid) session_uid,local_date FROM calendar_session_revisions WHERE session_uid=ANY($1) AND calendar_version_number<=(SELECT calendar_head_version FROM app_state WHERE id=1) ORDER BY session_uid,calendar_version_number DESC,revision DESC)p`, s.manual)
		if err != nil {
			return err
		}
		for _, d := range days {
			began[d] = true
		}
		matched, err = rematch.Dates(ctx, tx, days, now)
		if err != nil {
			return err
		}
	}
	if (len(matched) > 0 || !manualOnly) && (!recoveryOnly || includeToday) {
		dates := maps.Clone(s.dates)
		for _, id := range s.manual {
			days, err := b.dateRows(`SELECT local_date::text FROM calendar_session_revisions WHERE session_uid=$1 ORDER BY calendar_version_number DESC,revision DESC LIMIT 2`, id)
			if err != nil {
				return err
			}
			for _, d := range days {
				dates[d] = true
			}
		}
		dates[today] = true
		for day := range began {
			delete(dates, day)
		}
		ids, err := rematch.Dates(ctx, tx, slices.Sorted(maps.Keys(dates)), now)
		if err != nil {
			return err
		}
		matched = append(matched, ids...)
	}
	if err := b.apply(s, matched, includeToday); err != nil {
		return err
	}
	_, err = prompts.Generate(ctx, tx, now)
	return err
}
