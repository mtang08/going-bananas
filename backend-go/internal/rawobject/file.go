// Package rawobject retains immutable provider bytes before a database transaction references them.
package rawobject

import (
	"bytes"
	"crypto/rand"
	"errors"
	"os"
	"path/filepath"
)

// Write makes a complete file visible atomically. A retry verifies existing bytes.
func Write(root, path string, b []byte) error {
	if !filepath.IsLocal(path) {
		return errors.New("invalid_raw_path")
	}
	if err := os.MkdirAll(root, 0700); err != nil {
		return err
	}
	fs, err := os.OpenRoot(root)
	if err != nil {
		return err
	}
	defer func() { _ = fs.Close() }()
	dir := filepath.Dir(path)
	if err := fs.MkdirAll(dir, 0700); err != nil {
		return err
	}
	existing, err := fs.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		tmpPath := filepath.Join(dir, ".raw-"+rand.Text())
		tmp, err := fs.OpenFile(tmpPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		defer func() { _ = fs.Remove(tmpPath) }()
		if _, err = tmp.Write(b); err == nil {
			err = tmp.Sync()
		}
		closeErr := tmp.Close()
		if err != nil {
			return err
		}
		if closeErr != nil {
			return closeErr
		}
		if err = fs.Link(tmpPath, path); err != nil && !errors.Is(err, os.ErrExist) {
			return err
		}
		existing, err = fs.ReadFile(path)
		if err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	if !bytes.Equal(existing, b) {
		return errors.New("raw_hash_mismatch")
	}
	return nil
}
