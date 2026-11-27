package coachdashboard

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestPythonFileCutoverPostgres(t *testing.T) {
	pool := workflowPool(t)
	ctx := t.Context()
	const mode = "file-cutover"
	private := t.TempDir()
	store := NewStore(pool, mode)
	// These fixtures were written by the original dashboard with synthetic messages.
	dir := filepath.Join(private, "coach-chat", mode)
	path := filepath.Join(dir, "reviews", "00000000-0000-0000-0000-000000000001.json")
	requireOK(t, os.MkdirAll(filepath.Dir(path), 0700))
	for source, target := range map[string]string{
		"state.json":    filepath.Join(dir, "state.json"),
		"archived.json": path,
	} {
		data, err := os.ReadFile(filepath.Join("testdata", "legacy-review", source))
		requireOK(t, err)
		requireOK(t, os.WriteFile(target, data, 0600))
	}
	lock, err := os.OpenFile(filepath.Join(dir, "turn.lock"), os.O_RDWR|os.O_CREATE, 0600)
	requireOK(t, err)
	requireOK(t, syscall.Flock(int(lock.Fd()), syscall.LOCK_EX))
	if err := store.ImportPythonFiles(ctx, private); err == nil {
		t.Fatal("imported during a live Python turn")
	}
	requireOK(t, lock.Close())
	raw, err := os.ReadFile(path)
	requireOK(t, err)
	requireOK(t, os.WriteFile(path, []byte("{"), 0600))
	if err := store.ImportPythonFiles(ctx, private); err == nil {
		t.Fatal("accepted broken archive")
	}
	var count int
	requireOK(t, pool.QueryRow(ctx, "SELECT count(*) FROM coach_chat_reviews WHERE mode=$1", mode).Scan(&count))
	if count != 0 {
		t.Fatal("partially imported review")
	}
	requireOK(t, os.WriteFile(path, raw, 0600))
	requireOK(t, store.ImportPythonFiles(ctx, private))
	r, err := store.Review(ctx)
	requireOK(t, err)
	if r.Status != "failed" || r.Error.Code != "interrupted" || r.ThreadID != "resume-2" || len(r.Messages) != 1 {
		t.Fatalf("lost resume state: %#v", r)
	}
	requireOK(t, store.NewReview(ctx, Guard{ID: r.ID, Set: true}))
	requireOK(t, store.ImportPythonFiles(ctx, private))
	current, err := store.Review(ctx)
	requireOK(t, err)
	if current.ID == r.ID || len(current.Messages) > 0 {
		t.Fatal("import resurrected archived review")
	}
	lease, err := store.Enqueue(ctx, Guard{Set: true, ID: r.ID}, "00000000-0000-0000-0000-00000000000b", "Synthetic message 1", "")
	requireOK(t, err)
	if lease != nil {
		lease.Close()
		t.Fatal("Python receipt started a second model turn")
	}
	requireOK(t, pool.QueryRow(ctx, "SELECT count(*) FROM coach_chat_reviews WHERE mode=$1 AND NOT current", mode).Scan(&count))
	if count != 2 {
		t.Fatalf("imported archive count %d", count)
	}
}

func TestImportRejectsRedirectedMode(t *testing.T) {
	private := t.TempDir()
	root := filepath.Join(private, "coach-chat")
	requireOK(t, os.MkdirAll(filepath.Join(root, "other"), 0700))
	requireOK(t, os.Symlink("other", filepath.Join(root, "test")))
	if _, err := pythonModeDir(private, "test"); err == nil {
		t.Fatal("followed redirected mode")
	}
}
