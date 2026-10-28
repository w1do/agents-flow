package agent

import (
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"html"
	"net/url"
	"regexp"
	"sort"
	"strings"
)

const redacted = "[redacted]"

var credentialText = regexp.MustCompile(`\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{6,}|(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{12,}|[A-Za-z][A-Za-z0-9_-]*_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{8,})\b`)
var privateKeyText = regexp.MustCompile(`(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)`)

type redactor struct {
	variants []string
	percent  []*regexp.Regexp
}

func newRedactor(token string) *redactor {
	r := &redactor{}
	if token == "" {
		return r
	}
	variants := map[string]bool{token: true}
	encode := func(value string) {
		for _, encoded := range []string{url.QueryEscape(value), url.PathEscape(value),
			base64.StdEncoding.EncodeToString([]byte(value)), base64.RawStdEncoding.EncodeToString([]byte(value)),
			base64.URLEncoding.EncodeToString([]byte(value)), base64.RawURLEncoding.EncodeToString([]byte(value)),
			hex.EncodeToString([]byte(value)), strings.ToUpper(hex.EncodeToString([]byte(value))), html.EscapeString(value)} {
			variants[encoded] = true
		}
	}
	encode(token)
	initial := make([]string, 0, len(variants))
	for value := range variants {
		initial = append(initial, value)
	}
	for _, value := range initial {
		encode(value)
	}
	var percent, unicode, escaped strings.Builder
	for _, value := range []byte(token) {
		fmt.Fprintf(&percent, "%%%02X", value)
		fmt.Fprintf(&unicode, `\u%04x`, value)
		fmt.Fprintf(&escaped, `\x%02x`, value)
	}
	variants[percent.String()], variants[unicode.String()], variants[escaped.String()] = true, true, true
	for value := range variants {
		if value == "" {
			continue
		}
		r.variants = append(r.variants, value)
	}
	sort.Slice(r.variants, func(i, j int) bool {
		if len(r.variants[i]) == len(r.variants[j]) {
			return r.variants[i] < r.variants[j]
		}
		return len(r.variants[i]) > len(r.variants[j])
	})
	for _, value := range r.variants {
		if strings.Contains(value, "%") {
			r.percent = append(r.percent, regexp.MustCompile("(?i)"+regexp.QuoteMeta(value)))
		}
	}
	return r
}

func (r *redactor) text(value string) string {
	if r.encodedSecret(value) {
		return redacted
	}
	value = privateKeyText.ReplaceAllString(value, redacted)
	value = authSecret.ReplaceAllString(value, redacted)
	value = credentialText.ReplaceAllString(value, redacted)
	for _, variant := range r.variants {
		parts := strings.Split(value, redacted)
		for i := range parts {
			parts[i] = strings.ReplaceAll(parts[i], variant, redacted)
		}
		value = strings.Join(parts, redacted)
	}
	for _, pattern := range r.percent {
		value = pattern.ReplaceAllString(value, redacted)
	}
	return value
}
