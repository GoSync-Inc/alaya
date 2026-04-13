package cmd

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

func TestCreateAPIKeyViaBootstrap_Success(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			t.Errorf("expected POST, got %s", r.Method)
		}
		if r.Header.Get("X-Api-Key") != "bootstrap_key_123" {
			t.Errorf("expected bootstrap key in X-Api-Key header, got %q", r.Header.Get("X-Api-Key"))
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"data": map[string]interface{}{
				"raw_key": "ak_newly_created_key",
			},
		})
	}))
	defer ts.Close()

	key, err := createAPIKeyViaBootstrap(ts.URL, "bootstrap_key_123")
	if err != nil {
		t.Fatalf("createAPIKeyViaBootstrap() error: %v", err)
	}
	if key != "ak_newly_created_key" {
		t.Errorf("expected raw_key, got %q", key)
	}
}

func TestCreateAPIKeyViaBootstrap_APIError(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"invalid bootstrap key"}`))
	}))
	defer ts.Close()

	_, err := createAPIKeyViaBootstrap(ts.URL, "wrong_bootstrap")
	if err == nil {
		t.Fatal("expected error for 401 response")
	}
}

func TestCreateAPIKeyViaBootstrap_MissingRawKey(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"data": map[string]interface{}{
				"id": "key-uuid",
			},
		})
	}))
	defer ts.Close()

	_, err := createAPIKeyViaBootstrap(ts.URL, "bootstrap_key_123")
	if err == nil {
		t.Fatal("expected error when raw_key is missing from response")
	}
}

func TestRenderAgentSetup_RedactsSecretByDefault(t *testing.T) {
	output := renderAgentSetup("generic", "https://alaya.example", "ak_super_secret", false)

	if !strings.Contains(output, "ALAYA_SERVER_URL=https://alaya.example") {
		t.Fatalf("expected server URL in output, got %q", output)
	}
	if !strings.Contains(output, "<stored in keyring; rerun with --show-secret to print>") {
		t.Fatalf("expected redaction placeholder in output, got %q", output)
	}
	if strings.Contains(output, "ak_super_secret") {
		t.Fatalf("expected secret to be redacted, got %q", output)
	}
}

func TestRenderAgentSetup_IncludesSecretWhenOptedIn(t *testing.T) {
	output := renderAgentSetup("codex", "https://alaya.example", "ak_super_secret", true)

	if !strings.Contains(output, "ALAYA_API_KEY=ak_super_secret") {
		t.Fatalf("expected secret in output, got %q", output)
	}
}

func TestWarnShowSecret_PrintsToStderr(t *testing.T) {
	cmd := &cobra.Command{}
	var stderr bytes.Buffer
	cmd.SetErr(&stderr)

	if err := warnShowSecret(cmd, true); err != nil {
		t.Fatalf("warnShowSecret() error: %v", err)
	}
	if !strings.Contains(stderr.String(), "--show-secret prints the API key to stdout") {
		t.Fatalf("expected warning on stderr, got %q", stderr.String())
	}
}

func TestWarnShowSecret_SkipsWhenDisabled(t *testing.T) {
	cmd := &cobra.Command{}
	var stderr bytes.Buffer
	cmd.SetErr(&stderr)

	if err := warnShowSecret(cmd, false); err != nil {
		t.Fatalf("warnShowSecret() error: %v", err)
	}
	if stderr.Len() != 0 {
		t.Fatalf("expected no stderr output, got %q", stderr.String())
	}
}
