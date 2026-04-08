package client

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
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
