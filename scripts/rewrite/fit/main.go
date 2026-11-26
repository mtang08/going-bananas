// Decode synthetic FIT from stdin for comparison with Garmin's Python SDK.
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"

	"github.com/muktihari/fit/decoder"
)

type result struct {
	Profile  uint16                      `json:"profile,omitempty"`
	Messages map[string][]map[string]any `json:"messages,omitempty"`
	Error    string                      `json:"error,omitempty"`
}

func decode() (result, error) {
	file, err := decoder.New(os.Stdin).Decode()
	if errors.Is(err, decoder.ErrCRCChecksumMismatch) {
		return result{Error: "invalid_crc"}, nil
	}
	if err != nil {
		return result{Error: "invalid_fit"}, nil
	}
	messages := make(map[string][]map[string]any)
	for _, message := range file.Messages {
		row := make(map[string]any)
		for _, field := range message.Fields {
			if !field.Value.Valid(field.BaseType) {
				continue
			}
			switch field.Name {
			case "position_lat", "position_long", "serial_number":
				continue
			}
			value := field.Value.Any()
			if field.Scale != 1 || field.Offset != 0 {
				number := reflect.ValueOf(value)
				floatType := reflect.TypeOf(float64(0))
				if !number.CanConvert(floatType) {
					return result{}, fmt.Errorf("unsupported scaled field %s", field.Name)
				}
				value = number.Convert(floatType).Float()/field.Scale - field.Offset
			}
			row[field.Name] = value
		}
		key := message.Num.String() + "_mesgs"
		messages[key] = append(messages[key], row)
	}
	return result{Profile: file.FileHeader.ProfileVersion, Messages: messages}, nil
}

func main() {
	got, err := decode()
	if err == nil {
		err = json.NewEncoder(os.Stdout).Encode(got)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
