package jsonx

import (
	"encoding/json"
	"testing"
)

func TestExactNumbersAtEveryDepth(t *testing.T) {
	data := []byte(`{"id":9007199254740993,"nested":[18446744073709551615,0.123456789012345678901]}`)
	var value map[string]any
	if err := Unmarshal(data, &value); err != nil {
		t.Fatal(err)
	}
	if value["id"] != json.Number("9007199254740993") {
		t.Fatal(value)
	}
	encoded, err := json.Marshal(value)
	if err != nil || string(encoded) != string(data) {
		t.Fatal("JSON numbers changed", string(encoded), err)
	}
}

func TestRejectsPartialAndMultipleValues(t *testing.T) {
	for _, data := range []string{`{} {}`, `{} garbage`, `{"id":`, ``} {
		if Unmarshal([]byte(data), new(any)) == nil {
			t.Fatal("invalid JSON accepted")
		}
	}
}
