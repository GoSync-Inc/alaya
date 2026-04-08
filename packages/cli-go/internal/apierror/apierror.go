package apierror

import (
	"errors"
	"fmt"
)

const (
	ExitGeneric   = 1
	ExitAuth      = 2
	ExitNotFound  = 3
	ExitTimeout   = 4
	ExitRateLimit = 5
)

// APIError is a structured HTTP API error carrying an exit code.
type APIError struct {
	StatusCode int
	ExitCode   int
	Body       string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("API error (%d): %s", e.StatusCode, e.Body)
}

// New creates an APIError with the appropriate exit code for the given HTTP status.
func New(statusCode int, body string) *APIError {
	exitCode := ExitGeneric
	switch {
	case statusCode == 401 || statusCode == 403:
		exitCode = ExitAuth
	case statusCode == 404:
		exitCode = ExitNotFound
	case statusCode == 429:
		exitCode = ExitRateLimit
	}
	return &APIError{StatusCode: statusCode, ExitCode: exitCode, Body: body}
}

// ExitCodeFrom extracts the appropriate CLI exit code from an error.
// Returns ExitGeneric for unknown errors and nil.
func ExitCodeFrom(err error) int {
	if err == nil {
		return ExitGeneric
	}
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		return apiErr.ExitCode
	}
	if isTimeout(err) {
		return ExitTimeout
	}
	return ExitGeneric
}

func isTimeout(err error) bool {
	var netErr interface{ Timeout() bool }
	return errors.As(err, &netErr) && netErr.Timeout()
}
