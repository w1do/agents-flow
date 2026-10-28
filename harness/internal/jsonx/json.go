// Package jsonx decodes one complete JSON value without rounding numbers.
package jsonx

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
)

func Unmarshal(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if err := decoder.Decode(new(any)); !errors.Is(err, io.EOF) {
		return errors.New("expected one complete JSON value")
	}
	return nil
}
