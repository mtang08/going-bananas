// Package backup reads and writes the version-one Python workspace archive format.
package backup

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

type File struct {
	SHA   string `json:"sha256"`
	Bytes int64  `json:"bytes"`
}
type Manifest struct {
	Version     int             `json:"version"`
	Created     string          `json:"created_at"`
	Credentials *bool           `json:"contains_credentials"`
	Files       map[string]File `json:"files"`
}

const maxEntry = 5 << 30
const maxTotal = 10 << 30

var roots = []string{"raw", "profile", "config", "research-imports"}

func allowed(name string) bool {
	parts := strings.Split(name, "/")
	if len(parts) < 3 || parts[0] != "private" || !fs.ValidPath(name) || strings.Contains(name, "\\") {
		return false
	}
	base := strings.ToLower(path.Base(name))
	if strings.Contains(base, "key") || strings.Contains(base, "token") || base == ".env" {
		return false
	}
	for _, r := range roots {
		if r == parts[1] {
			return true
		}
	}
	return false
}

func addFile(t *tar.Writer, file, name string) (File, error) {
	f, e := os.Open(file)
	if e != nil {
		return File{}, e
	}
	defer func() { _ = f.Close() }()
	s, e := f.Stat()
	if e != nil {
		return File{}, e
	}
	if !s.Mode().IsRegular() || s.Size() > maxEntry {
		return File{}, errors.New("unsafe_backup_entry")
	}
	e = t.WriteHeader(&tar.Header{Name: name, Mode: 0600, Size: s.Size()})
	if e != nil {
		return File{}, e
	}
	h := sha256.New()
	n, e := io.Copy(io.MultiWriter(t, h), f)
	return File{hex.EncodeToString(h.Sum(nil)), n}, e
}

func writeArchive(dst io.Writer, private, dump string) (Manifest, error) {
	gz := gzip.NewWriter(dst)
	t := tar.NewWriter(gz)
	credentials := false
	m := Manifest{1, time.Now().UTC().Format(time.RFC3339Nano), &credentials, map[string]File{}}
	var total int64
	add := func(file, name string) error {
		item, err := addFile(t, file, name)
		if err != nil {
			return err
		}
		total += item.Bytes
		if total > maxTotal || len(m.Files) >= 10000 {
			return errors.New("backup_too_large")
		}
		m.Files[name] = item
		return nil
	}
	if err := add(dump, "database.pgdump"); err != nil {
		return m, err
	}
	for _, r := range roots {
		root := filepath.Join(private, r)
		err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if os.IsNotExist(err) && p == root {
				return nil
			}
			if err != nil {
				return err
			}
			if d.Type()&fs.ModeSymlink != 0 {
				return errors.New("private_symlink")
			}
			if d.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(private, p)
			if err != nil {
				return err
			}
			name := "private/" + filepath.ToSlash(rel)
			if !d.Type().IsRegular() || !allowed(name) {
				return nil
			}
			return add(p, name)
		})
		if err != nil {
			return m, err
		}
	}
	data, err := json.Marshal(m)
	if err != nil {
		return m, err
	}
	if err = t.WriteHeader(&tar.Header{Name: "manifest.json", Mode: 0600, Size: int64(len(data))}); err != nil {
		return m, err
	}
	if _, err = t.Write(data); err != nil {
		return m, err
	}
	if err = t.Close(); err != nil {
		return m, err
	}
	return m, gz.Close()
}

// unpack validates checksums in a new private staging directory before any database writes.
func unpack(archive, stage string) (Manifest, error) {
	var m Manifest
	f, err := os.Open(archive)
	if err != nil {
		return m, err
	}
	defer func() { _ = f.Close() }()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return m, err
	}
	defer func() { _ = gz.Close() }()
	t := tar.NewReader(gz)
	got := map[string]File{}
	seen := false
	var total int64
	for {
		h, e := t.Next()
		if errors.Is(e, io.EOF) {
			break
		}
		if e != nil {
			return m, e
		}
		total += h.Size
		if h.Typeflag != tar.TypeReg || h.Size > maxEntry || total > maxTotal {
			return m, errors.New("unsafe_backup_entry")
		}
		if h.Name == "manifest.json" {
			if seen || h.Size > 4<<20 {
				return m, errors.New("invalid_backup_manifest")
			}
			seen = true
			data, e := io.ReadAll(t)
			if e != nil {
				return m, e
			}
			if e = json.Unmarshal(data, &m); e != nil {
				return m, errors.New("invalid_backup_manifest")
			}
			continue
		}
		if h.Name != "database.pgdump" && !allowed(h.Name) {
			return m, errors.New("unsafe_backup_entry")
		}
		if _, dup := got[h.Name]; dup || len(got) >= 10000 {
			return m, errors.New("backup_size_or_duplicate")
		}
		dest := filepath.Join(stage, filepath.FromSlash(h.Name))
		if e = os.MkdirAll(filepath.Dir(dest), 0700); e != nil {
			return m, e
		}
		out, e := os.OpenFile(dest, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			return m, e
		}
		hash := sha256.New()
		n, e := io.Copy(io.MultiWriter(out, hash), t)
		closeErr := out.Close()
		if e != nil {
			return m, e
		}
		if closeErr != nil {
			return m, closeErr
		}
		got[h.Name] = File{hex.EncodeToString(hash.Sum(nil)), n}
	}
	// Read through the gzip trailer to verify its checksum.
	if tail, e := io.Copy(io.Discard, io.LimitReader(gz, 10241)); e != nil || tail > 10240 {
		return m, errors.New("invalid_backup_trailer")
	}
	if m.Version != 1 || m.Credentials == nil || *m.Credentials {
		return m, errors.New("unsupported_backup_version")
	}
	if _, ok := got["database.pgdump"]; !ok || len(got) != len(m.Files) {
		return m, errors.New("backup_manifest_mismatch")
	}
	for name, details := range got {
		if details != m.Files[name] {
			return m, errors.New("backup_checksum_mismatch")
		}
	}
	return m, nil
}
