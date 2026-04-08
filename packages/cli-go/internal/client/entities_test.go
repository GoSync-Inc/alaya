package client

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestListEntities(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" {
			t.Errorf("expected GET, got %s", r.Method)
		}
		if r.URL.Path != "/api/v1/entities" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		resp := EntityListResponse{
			Data: []Entity{
				{ID: "e1", Name: "Alice", EntityType: "person", Aliases: []string{}},
			},
			Pagination: Pagination{HasMore: false, Count: 1},
		}
		json.NewEncoder(w).Encode(resp)
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	resp, err := c.ListEntities("", 20)
	if err != nil {
		t.Fatalf("ListEntities() error: %v", err)
	}
	if len(resp.Data) != 1 {
		t.Fatalf("expected 1 entity, got %d", len(resp.Data))
	}
	if resp.Data[0].Name != "Alice" {
		t.Errorf("unexpected name: %q", resp.Data[0].Name)
	}
}

func TestListEntities_WithCursor(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cursor := r.URL.Query().Get("cursor")
		if cursor != "token123" {
			t.Errorf("expected cursor=token123, got %q", cursor)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(EntityListResponse{Data: []Entity{}, Pagination: Pagination{}})
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	_, err := c.ListEntities("token123", 10)
	if err != nil {
		t.Fatalf("ListEntities() error: %v", err)
	}
}

func TestGetEntity(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/entities/e1" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"id":"e1","name":"Alice","entity_type_id":"person","is_deleted":false,"aliases":[]}`))
	}))
	defer ts.Close()

	c := New(ts.URL, "ak_test")
	data, err := c.GetEntity("e1")
	if err != nil {
		t.Fatalf("GetEntity() error: %v", err)
	}
	var entity Entity
	if err := json.Unmarshal(data, &entity); err != nil {
		t.Fatalf("unmarshal entity: %v", err)
	}
	if entity.ID != "e1" {
		t.Errorf("unexpected id: %q", entity.ID)
	}
}
