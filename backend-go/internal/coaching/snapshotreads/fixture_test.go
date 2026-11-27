package snapshotreads

import (
	"os"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

// Fixtures preserve synthetic setup and full contract responses captured from
// the retired domain implementation. Each scenario rolls back its own setup.
func snapshotFixture(t *testing.T, name string) (pgx.Tx, []byte) {
	t.Helper()
	tx := testpg.DashboardTx(t)
	loadSeed(t, tx, name)
	return tx, fixtureFile(t, name+".json")
}

func loadSeed(t *testing.T, tx pgx.Tx, name string) {
	t.Helper()
	if _, err := tx.Exec(t.Context(), string(fixtureFile(t, name+".sql"))); err != nil {
		t.Fatal(err)
	}
}

func fixtureFile(t *testing.T, name string) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}
