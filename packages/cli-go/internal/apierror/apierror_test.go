package apierror

import (
	"errors"
	"fmt"
	"net"
	"testing"
)

func TestNew_MessageFormat(t *testing.T) {
	err := New(404, "not found body")
	if err.Error() != "API error (404): not found body" {
		t.Errorf("unexpected error message: %q", err.Error())
	}
}

func TestNew_ExitCodes(t *testing.T) {
	cases := []struct {
		status   int
		wantCode int
	}{
		{200, ExitGeneric}, // shouldn't normally be used but safe
		{400, ExitGeneric},
		{401, ExitAuth},
		{403, ExitAuth},
		{404, ExitNotFound},
		{429, ExitRateLimit},
		{500, ExitGeneric},
	}
	for _, tc := range cases {
		err := New(tc.status, "body")
		if err.ExitCode != tc.wantCode {
			t.Errorf("status %d: expected exit code %d, got %d", tc.status, tc.wantCode, err.ExitCode)
		}
	}
}

func TestExitCodeFrom_APIError(t *testing.T) {
	err := New(401, "unauthorized")
	code := ExitCodeFrom(err)
	if code != ExitAuth {
		t.Errorf("expected %d, got %d", ExitAuth, code)
	}
}

func TestExitCodeFrom_WrappedAPIError(t *testing.T) {
	apiErr := New(404, "not found")
	wrapped := fmt.Errorf("operation failed: %w", apiErr)
	code := ExitCodeFrom(wrapped)
	if code != ExitNotFound {
		t.Errorf("expected %d, got %d", ExitNotFound, code)
	}
}

func TestExitCodeFrom_TimeoutError(t *testing.T) {
	// net.Error with Timeout() = true
	timeoutErr := &net.OpError{
		Op:  "dial",
		Err: &timeoutSentinel{},
	}
	code := ExitCodeFrom(timeoutErr)
	if code != ExitTimeout {
		t.Errorf("expected %d, got %d", ExitTimeout, code)
	}
}

func TestExitCodeFrom_GenericError(t *testing.T) {
	code := ExitCodeFrom(errors.New("some error"))
	if code != ExitGeneric {
		t.Errorf("expected %d, got %d", ExitGeneric, code)
	}
}

func TestExitCodeFrom_Nil(t *testing.T) {
	code := ExitCodeFrom(nil)
	if code != ExitGeneric {
		t.Errorf("expected %d for nil, got %d", ExitGeneric, code)
	}
}

// timeoutSentinel is a net.Error that reports Timeout() = true.
type timeoutSentinel struct{}

func (t *timeoutSentinel) Error() string   { return "timeout" }
func (t *timeoutSentinel) Timeout() bool   { return true }
func (t *timeoutSentinel) Temporary() bool { return true }
