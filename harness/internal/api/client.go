package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"log"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type Options struct {
	HTTPClient    *http.Client
	MaxAttempts   int
	Backoff       time.Duration
	AllowInsecure bool
}

type Client struct {
	base, token string
	http        *http.Client
	attempts    int
	backoff     time.Duration
}

// New uses bounded retries and refuses redirects so credentials stay on this server.
func New(base, token string, options Options) (*Client, error) {
	if err := ValidateURLWithInsecure(base, options.AllowInsecure); err != nil {
		return nil, err
	}
	if strings.HasPrefix(strings.ToLower(base), "http://") {
		log.Print("WARNING: HTTP transport is insecure; credentials may be sent without TLS")
	}
	if strings.ContainsAny(token, "\r\n") {
		return nil, errors.New("invalid agent token")
	}
	h := http.Client{Timeout: 10 * time.Second}
	if options.HTTPClient != nil {
		h = *options.HTTPClient
		if h.Timeout <= 0 {
			h.Timeout = 10 * time.Second
		}
	}
	h.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	if options.MaxAttempts <= 0 {
		options.MaxAttempts = 3
	}
	if options.Backoff <= 0 {
		options.Backoff = 200 * time.Millisecond
	}
	return &Client{strings.TrimRight(base, "/"), token, &h, options.MaxAttempts, options.Backoff}, nil
}

func ValidateURL(value string) error {
	return ValidateURLWithInsecure(value, false)
}

func ValidateURLWithInsecure(value string, allowInsecure bool) error {
	u, err := url.Parse(value)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" ||
		u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errors.New("server_url must be an HTTP(S) URL without credentials, query or fragment")
	}
	if u.Scheme == "http" && !allowInsecure && !loopbackHost(u.Hostname()) {
		return errors.New("server_url must use HTTPS unless it targets loopback or allow_insecure is enabled")
	}
	return nil
}

func loopbackHost(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

type Error struct {
	StatusCode   int
	TaskFinished bool
}

// Never include response bodies: they can contain credentials or skill content.
func (e *Error) Error() string {
	return "server returned HTTP " + strconv.Itoa(e.StatusCode) + " (" + http.StatusText(e.StatusCode) + ")"
}

func NewKey() string {
	var value [16]byte
	// Failure of the OS random source is unrecoverable on supported Go platforms.
	_, _ = rand.Read(value[:])
	return hex.EncodeToString(value[:])
}

func wait(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
