package agent

import (
	"encoding/base64"
	"html"
	"regexp"
	"strconv"
	"strings"
)

var escapedByte = regexp.MustCompile(`\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2})`)
var escapedPercent = regexp.MustCompile(`%[0-9a-fA-F]{2}`)
var base64Fragment = regexp.MustCompile(`[A-Za-z0-9_+/=-]{8,}`)
var dataBase64Prefix = regexp.MustCompile(`(?i)\bdata:[^,\s]*;base64,`)
var base64Prefix = regexp.MustCompile(`(?i)\b(?:b64=|base64[:,])`)

const maxBase64FragmentBytes = 64 << 10

// Canonicalization also handles partial/mixed escaping, which enumerating
// whole-token encodings cannot cover. A detected encoded secret masks its field.
func (r *redactor) encodedSecret(value string) bool {
	if r.base64Secret(value) {
		return true
	}
	if !strings.ContainsAny(value, `%&\`) {
		return false
	}
	for range 3 {
		decoded := html.UnescapeString(value)
		decoded = escapedPercent.ReplaceAllStringFunc(decoded, func(escape string) string {
			code, _ := strconv.ParseUint(escape[1:], 16, 8)
			return string([]byte{byte(code)})
		})
		decoded = escapedByte.ReplaceAllStringFunc(decoded, func(escape string) string {
			code, _ := strconv.ParseUint(escape[2:], 16, 32)
			return string(rune(code))
		})
		if decoded == value {
			return false
		}
		for _, known := range r.variants {
			if strings.Contains(decoded, known) {
				return true
			}
		}
		if credentialText.MatchString(decoded) || privateKeyText.MatchString(decoded) {
			return true
		}
		value = decoded
	}
	return false
}

func (r *redactor) base64Secret(value string) bool {
	value = dataBase64Prefix.ReplaceAllString(value, "")
	value = base64Prefix.ReplaceAllString(value, "")
	for _, fragment := range base64Fragment.FindAllString(value, -1) {
		if r.base64FragmentSecret(fragment) {
			return true
		}
	}
	return false
}

func (r *redactor) base64FragmentSecret(fragment string) bool {
	overlap := 8
	for _, variant := range r.variants {
		encodedBytes := (len(variant)*4 + 2) / 3
		if needed := encodedBytes + 8; needed > overlap {
			overlap = needed
		}
	}
	overlap = (overlap + 3) &^ 3
	windowBytes := maxBase64FragmentBytes
	if overlap+4 > windowBytes {
		windowBytes = overlap + 4
	}
	for start := 0; start < len(fragment); {
		end := start + windowBytes
		if end >= len(fragment) {
			end = len(fragment)
		} else {
			end -= (end - start) % 4
		}
		candidate := strings.TrimRight(fragment[start:end], "=")
		if decoded, ok := decodeBase64(candidate); ok && r.decodedSecret(decoded) {
			return true
		}
		if end == len(fragment) {
			break
		}
		start = end - overlap
		start -= start % 4
	}
	return false
}

func decodeBase64(value string) ([]byte, bool) {
	for _, encoding := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding,
		base64.URLEncoding, base64.RawURLEncoding} {
		if decoded, err := encoding.DecodeString(value); err == nil {
			return decoded, true
		}
	}
	return nil, false
}

func (r *redactor) decodedSecret(value []byte) bool {
	decoded := string(value)
	for _, known := range r.variants {
		if strings.Contains(decoded, known) {
			return true
		}
	}
	return credentialText.Match(value) || privateKeyText.Match(value) || authSecret.MatchString(decoded)
}
