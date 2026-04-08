package cmd

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
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
			"raw_key": "ak_newly_created_key",
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
		// Response missing raw_key field
		json.NewEncoder(w).Encode(map[string]interface{}{
			"id": "key-uuid",
		})
	}))
	defer ts.Close()

	_, err := createAPIKeyViaBootstrap(ts.URL, "bootstrap_key_123")
	if err == nil {
		t.Fatal("expected error when raw_key is missing from response")
	}
}
