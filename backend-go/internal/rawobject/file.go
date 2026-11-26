// Package rawobject retains immutable provider bytes before a database transaction references them.
package rawobject

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
)

// Write makes a complete file visible atomically. A retry verifies existing bytes.
func Write(root, path string, b []byte) error {
	if !filepath.IsLocal(path) {
		return errors.New("invalid_raw_path")
	}
	target := filepath.Join(root, path)
	dir := filepath.Dir(target)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	existing, err := os.ReadFile(target)
	if errors.Is(err, os.ErrNotExist) {
		tmp, err := os.CreateTemp(dir, ".raw-*")
		if err != nil {
			return err
		}
		defer func() { _ = os.Remove(tmp.Name()) }()
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
		if err = os.Link(tmp.Name(), target); err != nil && !errors.Is(err, os.ErrExist) {
			return err
		}
		existing, err = os.ReadFile(target)
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
