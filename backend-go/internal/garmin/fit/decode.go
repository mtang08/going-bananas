// Package fit decodes a downloaded Garmin FIT archive without writing its contents to disk.
package fit

import (
	"archive/zip"
	"bytes"
	"compress/bzip2"
	"encoding/binary"
	"hash/crc32"
	"io"
	"strings"

	"github.com/muktihari/fit/decoder"
	"github.com/muktihari/fit/kit/hash/crc16"
)

// SDKVersion identifies the native FIT module used to decode this activity.
const SDKVersion = "github.com/muktihari/fit v0.28.7"
const maxFITBytes = 50 * 1024 * 1024

// DecodeError identifies a stable failure code shared with the Python adapter.
type DecodeError struct{ Code string }

func (e *DecodeError) Error() string { return e.Code }

func decodeError(code string) error { return &DecodeError{Code: code} }

// DecodeZIP extracts the single FIT member and decodes its activity.
func DecodeZIP(archive []byte) (*DecodedFit, error) {
	payload, err := extractFIT(archive)
	if err != nil {
		return nil, err
	}
	rows := messageRows{projectedMessages: newProjection()}
	remaining := payload
	for {
		size, err := verifiedSize(remaining, len(remaining) == len(payload))
		if err != nil {
			if len(remaining) == len(payload) {
				return nil, err
			}
			return nil, decodeError("decode_failed")
		}
		if binary.LittleEndian.Uint32(remaining[4:8]) != 0 {
			d := decoder.New(bytes.NewReader(remaining[:size]), decoder.WithIgnoreChecksum(),
				decoder.WithBroadcastOnly(), decoder.WithMesgDefListener(&rows),
				decoder.WithMesgListener(&rows), decoder.WithFactory(&rows))
			if _, err := d.Decode(); err != nil || rows.invalid {
				return nil, decodeError("decode_failed")
			}
		}
		remaining = remaining[size:]
		if len(remaining) == 0 {
			break
		}
	}
	return rows.normalize(payload)
}

func extractFIT(data []byte) ([]byte, error) {
	r, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, decodeError("bad_zip")
	}
	r.RegisterDecompressor(12, func(source io.Reader) io.ReadCloser { return io.NopCloser(bzip2.NewReader(source)) })
	var member *zip.File
	for _, f := range r.File {
		if !strings.HasSuffix(strings.ToLower(f.Name), ".fit") {
			continue
		}
		if member != nil {
			return nil, decodeError("zip_member_count")
		}
		member = f
	}
	if member == nil {
		return nil, decodeError("zip_member_count")
	}
	if member.UncompressedSize64 > maxFITBytes {
		return nil, decodeError("zip_member_too_large")
	}
	// The download path supplies no ZIP password or decoder for patched data.
	const encryptedOrPatched = 1 | (1 << 5) | (1 << 6)
	if member.Flags&encryptedOrPatched != 0 {
		return nil, decodeError("bad_zip")
	}
	rc, err := member.Open()
	if err != nil {
		return nil, decodeError("bad_zip")
	}
	payload, readErr := readBounded(rc, maxFITBytes)
	closeErr := rc.Close()
	if readErr != nil {
		return nil, readErr
	}
	if closeErr != nil {
		return nil, decodeError("bad_zip")
	}
	// archive/zip permits a zero CRC as an unset value when there is no descriptor.
	if member.CRC32 == 0 && crc32.ChecksumIEEE(payload) != 0 {
		return nil, decodeError("bad_zip")
	}
	return payload, nil
}

func readBounded(source io.Reader, limit int64) ([]byte, error) {
	payload, err := io.ReadAll(io.LimitReader(source, limit+1))
	if int64(len(payload)) > limit {
		return nil, decodeError("zip_member_too_large")
	}
	if err != nil {
		return nil, decodeError("bad_zip")
	}
	return payload, nil
}

// The reference distinguishes an unrecognizable header, a damaged first file,
// and failures encountered during message decoding (including subsequent files).
func verifiedSize(p []byte, first bool) (int, error) {
	if len(p) < 14 || (p[0] != 12 && p[0] != 14) || len(p) < int(p[0])+2 || string(p[8:12]) != ".FIT" {
		return 0, decodeError("invalid_fit")
	}
	end := uint64(p[0]) + uint64(binary.LittleEndian.Uint32(p[4:8]))
	if end+2 > uint64(len(p)) {
		return 0, decodeError("invalid_crc")
	}
	if first && p[0] == 14 && checksum(p[:12]) != binary.LittleEndian.Uint16(p[12:14]) {
		return 0, decodeError("invalid_crc")
	}
	if checksum(p[:end]) != binary.LittleEndian.Uint16(p[end:]) {
		return 0, decodeError("invalid_crc")
	}
	return int(end + 2), nil
}

func checksum(p []byte) uint16 {
	h := crc16.New()
	_, _ = h.Write(p)
	return h.Sum16()
}
