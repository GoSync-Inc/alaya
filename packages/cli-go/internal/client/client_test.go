package client

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/apierror"
)

func TestNew(t *testing.T) {
	c := New("http://localhost:8000", "ak_test")
	if c.BaseURL != "http://localhost:8000" {
		t.Errorf("unexpected BaseURL: %q", c.BaseURL)
	}
	if c.APIKey != "ak_test" {
		t.Errorf("unexpected APIKey: %q", c.APIKey)
	}
	if c.HTTPClient == nil {
		t.Error("HTTPClient should not be nil")
	}
}

func TestPost_Success(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			t.Errorf("expected POST, got %s", r.Method)
		}
		if r.Header.Get("X-Api-Key") != "ak_test" {
			t.Errorf("missing or wrong X-Api-Key header")
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("missing Content-Type header")
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"ok":true}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	data, err := c.Post("/search", map[string]string{"query": "test"})
	if err != nil {
		t.Fatalf("Post() error: %v", err)
	}
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if result["ok"] != true {
		t.Errorf("unexpected response body: %v", result)
	}
}

func TestPost_ErrorStatus(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"unauthorized"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "bad_key")
	_, err := c.Post("/search", map[string]string{})
	if err == nil {
		t.Fatal("expected error for 401 response")
	}
}

func TestSearch(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		resp := SearchResponse{
			Query:     "who leads the project",
			Total:     1,
			ElapsedMs: 42,
			Results: []EvidenceUnit{
				{SourceType: "claim", SourceID: "abc", Content: "Alice leads Project Alpha", Score: 0.95},
			},
		}
		json.NewEncoder(w).Encode(resp)
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	resp, err := c.Search(SearchRequest{Query: "who leads the project", Limit: 5})
	if err != nil {
		t.Fatalf("Search() error: %v", err)
	}
	if resp.Query != "who leads the project" {
		t.Errorf("unexpected query: %q", resp.Query)
	}
	if resp.Total != 1 {
		t.Errorf("unexpected total: %d", resp.Total)
	}
	if len(resp.Results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(resp.Results))
	}
	if resp.Results[0].Score != 0.95 {
		t.Errorf("unexpected score: %f", resp.Results[0].Score)
	}
}

func TestGet_Success(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			t.Errorf("expected GET, got %s", r.Method)
		}
		if r.Header.Get("X-Api-Key") != "ak_test" {
			t.Errorf("missing or wrong X-Api-Key header")
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"id":"abc"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	data, err := c.Get("/entities/abc")
	if err != nil {
		t.Fatalf("Get() error: %v", err)
	}
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if result["id"] != "abc" {
		t.Errorf("unexpected response body: %v", result)
	}
}

func TestGet_ErrorStatus(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"error":"not found"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	_, err := c.Get("/entities/missing")
	if err == nil {
		t.Fatal("expected error for 404 response")
	}
}

func TestGet_Returns_APIError_404(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"error":"not found"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	_, err := c.Get("/entities/missing")
	var apiErr *apierror.APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *apierror.APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != 404 {
		t.Errorf("expected status 404, got %d", apiErr.StatusCode)
	}
	if apiErr.ExitCode != apierror.ExitNotFound {
		t.Errorf("expected ExitNotFound (%d), got %d", apierror.ExitNotFound, apiErr.ExitCode)
	}
}

func TestPost_Returns_APIError_401(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"unauthorized"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "bad_key")
	_, err := c.Post("/search", map[string]string{})
	var apiErr *apierror.APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *apierror.APIError, got %T: %v", err, err)
	}
	if apiErr.ExitCode != apierror.ExitAuth {
		t.Errorf("expected ExitAuth (%d), got %d", apierror.ExitAuth, apiErr.ExitCode)
	}
}

func TestDelete_Returns_APIError_429(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		w.Write([]byte(`{"error":"rate limited"}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	_, err := c.Delete("/api-keys/ak_prefix")
	var apiErr *apierror.APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected *apierror.APIError, got %T: %v", err, err)
	}
	if apiErr.ExitCode != apierror.ExitRateLimit {
		t.Errorf("expected ExitRateLimit (%d), got %d", apierror.ExitRateLimit, apiErr.ExitCode)
	}
}

func TestAsk(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		resp := AskResponse{
			Answer:     "Alice leads Project Alpha.",
			Answerable: true,
			TokensUsed: 100,
		}
		json.NewEncoder(w).Encode(resp)
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	resp, err := c.Ask(AskRequest{Question: "Who leads Project Alpha?", MaxResults: 3})
	if err != nil {
		t.Fatalf("Ask() error: %v", err)
	}
	if !resp.Answerable {
		t.Error("expected answerable=true")
	}
	if resp.Answer == "" {
		t.Error("expected non-empty answer")
	}
	if resp.TokensUsed != 100 {
		t.Errorf("unexpected tokens_used: %d", resp.TokensUsed)
	}
}
