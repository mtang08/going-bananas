// Package zipinput reads selected Garmin download/export members in memory.
package zipinput

import (
	"archive/zip"
	"bytes"
	"compress/bzip2"
	"encoding/binary"
	"io"
	"strings"
	"unicode/utf8"

	"github.com/ulikunitz/xz/lzma"
	"golang.org/x/text/encoding/charmap"
)

// Reader opens members sequentially. The standard library resolves prepended
// bytes, ZIP64 offsets and data descriptors from the central directory.
type Reader struct {
	*zip.Reader
	source *headerReader
	size   int64
}

type headerReader struct {
	source       io.ReaderAt
	headerOffset int64
}

func (r *headerReader) ReadAt(p []byte, off int64) (int, error) {
	n, err := r.source.ReadAt(p, off)
	// File.DataOffset reads the fixed local header, but doesn't expose its
	// offset or compare its filename with the central directory's name.
	if n == 30 && string(p[:4]) == "PK\x03\x04" {
		r.headerOffset = off
	}
	return n, err
}

func New(data []byte) (*Reader, error) {
	return NewReaderAt(bytes.NewReader(data), int64(len(data)))
}

func NewReaderAt(input io.ReaderAt, size int64) (*Reader, error) {
	source := &headerReader{source: input}
	r, err := zip.NewReader(source, size)
	if err != nil {
		return nil, err
	}
	r.RegisterDecompressor(12, func(src io.Reader) io.ReadCloser { return io.NopCloser(bzip2.NewReader(src)) })
	return &Reader{Reader: r, source: source, size: size}, nil
}

func decodeName(raw string, flags uint16) (string, error) {
	if flags&(1<<11) != 0 {
		if !utf8.ValidString(raw) {
			return "", zip.ErrFormat
		}
		return raw, nil
	}
	return charmap.CodePage437.NewDecoder().String(raw)
}

func Name(f *zip.File) (string, error) {
	name, err := decodeName(f.Name, f.Flags)
	name, _, _ = strings.Cut(name, "\x00")
	return name, err
}

func (r *Reader) OpenMember(f *zip.File) (io.ReadCloser, error) {
	if f.Flags&(1|1<<5|1<<6) != 0 {
		return nil, zip.ErrAlgorithm
	}
	r.source.headerOffset = -1
	dataOffset, err := f.DataOffset()
	header := r.source.headerOffset
	if err != nil || header < 0 || dataOffset > r.size || dataOffset < header+30 {
		return nil, zip.ErrFormat
	}
	b := make([]byte, dataOffset-header)
	if _, err := r.source.source.ReadAt(b, header); err != nil {
		return nil, zip.ErrFormat
	}
	nameEnd := 30 + int(binary.LittleEndian.Uint16(b[26:28]))
	if nameEnd > len(b) {
		return nil, zip.ErrFormat
	}
	local, err := decodeName(string(b[30:nameEnd]), binary.LittleEndian.Uint16(b[6:8]))
	if err != nil {
		return nil, err
	}
	central, err := decodeName(f.Name, f.Flags)
	if err != nil || local != central {
		return nil, zip.ErrFormat
	}
	if f.Method == 14 {
		r.RegisterDecompressor(14, func(src io.Reader) io.ReadCloser { return openLZMA(src, f.UncompressedSize64) })
	}
	return f.Open()
}

// ZIP method 14 prefixes raw LZMA1 data with an SDK version, a little-endian
// property length, and five LZMA properties. Classic LZMA uses those same
// properties followed by the unpacked size, which ZIP already provides.
func openLZMA(src io.Reader, size uint64) io.ReadCloser {
	var prefix [9]byte
	if _, err := io.ReadFull(src, prefix[:]); err != nil || binary.LittleEndian.Uint16(prefix[2:4]) != 5 {
		return failedReader{}
	}
	var header [13]byte
	copy(header[:5], prefix[4:])
	// No match can refer farther back than the entire uncompressed member.
	dict := min(uint64(binary.LittleEndian.Uint32(header[1:5])), size)
	binary.LittleEndian.PutUint32(header[1:5], uint32(max(dict, 4096)))
	binary.LittleEndian.PutUint64(header[5:], size)
	reader, err := lzma.NewReader(io.MultiReader(bytes.NewReader(header[:]), src))
	if err != nil {
		return failedReader{}
	}
	return io.NopCloser(reader)
}

type failedReader struct{}

func (failedReader) Read([]byte) (int, error) { return 0, zip.ErrFormat }
func (failedReader) Close() error             { return nil }
