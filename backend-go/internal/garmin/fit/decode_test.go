package fit

import (
	"errors"
	"strings"
	"testing"
)

func TestReadBounded(t *testing.T) {
	if data, err := readBounded(strings.NewReader("abcd"), 4); err != nil || string(data) != "abcd" {
		t.Fatalf("exact limit: got %q, %v", data, err)
	}
	data, err := readBounded(strings.NewReader("abcde"), 4)
	var failure *DecodeError
	if data != nil || !errors.As(err, &failure) || failure.Code != "zip_member_too_large" {
		t.Fatalf("past limit: got %q, %v", data, err)
	}
}
