package snapshotreads

import (
	"context"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/athleteprofile"
)

type Profile = athleteprofile.Profile
type ProfileMetadata = athleteprofile.ProfileMetadata

func LoadProfile(ctx context.Context, tx pgx.Tx, asOf string) (Profile, error) {
	return athleteprofile.LoadProfile(ctx, tx, asOf)
}
