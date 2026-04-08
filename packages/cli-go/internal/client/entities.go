package client

import (
	"encoding/json"
	"fmt"
)

type Entity struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description *string  `json:"description,omitempty"`
	EntityType  string   `json:"entity_type_id"`
	IsDeleted   bool     `json:"is_deleted"`
	Aliases     []string `json:"aliases"`
}

type Pagination struct {
	NextCursor *string `json:"next_cursor"`
	HasMore    bool    `json:"has_more"`
	Count      int     `json:"count"`
}

type EntityListResponse struct {
	Data       []Entity   `json:"data"`
	Pagination Pagination `json:"pagination"`
}

func (c *Client) ListEntities(cursor string, limit int) (*EntityListResponse, error) {
	path := fmt.Sprintf("/entities?limit=%d", limit)
	if cursor != "" {
		path += "&cursor=" + cursor
	}
	data, err := c.Get(path)
	if err != nil {
		return nil, err
	}
	var resp EntityListResponse
	return &resp, json.Unmarshal(data, &resp)
}

func (c *Client) GetEntity(id string) ([]byte, error) {
	return c.Get("/entities/" + id)
}
