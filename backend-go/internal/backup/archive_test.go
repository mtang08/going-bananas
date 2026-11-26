package backup

import (
	"archive/tar"
	"compress/gzip"
	"os"
	"path/filepath"
	"testing"
)

func TestInvalidArchive(t *testing.T) {
	for _, test := range []struct {
		label    string
		entries  []string
		manifest string
		want     string
	}{
		{"path", []string{"private/raw/../leak"}, "{}", "unsafe_backup_entry"},
		{"credential", []string{"private/config/token.json"}, "{}", "unsafe_backup_entry"},
		{"duplicate", []string{"database.pgdump", "database.pgdump"}, "{}", "backup_size_or_duplicate"},
		{"corrupt", []string{"database.pgdump"}, `{"version":1,"contains_credentials":false,"files":{"database.pgdump":{"bytes":1,"sha256":"invalid"}}}`, "backup_checksum_mismatch"},
	} {
		t.Run(test.label, func(t *testing.T) {
			dir := t.TempDir()
			p := filepath.Join(dir, "archive")
			f, e := os.Create(p)
			if e != nil {
				t.Fatal(e)
			}
			gz := gzip.NewWriter(f)
			w := tar.NewWriter(gz)
			write := func(name, body string) {
				t.Helper()
				if err := w.WriteHeader(&tar.Header{Name: name, Mode: 0600, Size: int64(len(body))}); err != nil {
					t.Fatal(err)
				}
				if _, err := w.Write([]byte(body)); err != nil {
					t.Fatal(err)
				}
			}
			for _, entry := range test.entries {
				write(entry, "x")
			}
			write("manifest.json", test.manifest)
			if e = w.Close(); e != nil {
				t.Fatal(e)
			}
			if e = gz.Close(); e != nil {
				t.Fatal(e)
			}
			if e = f.Close(); e != nil {
				t.Fatal(e)
			}
			if _, err := unpack(p, dir); err == nil || err.Error() != test.want {
				t.Fatalf("got %v, want %v", err, test.want)
			}
		})
	}
}
