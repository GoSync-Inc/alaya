package client

import (
	"encoding/json"
	"fmt"
)

type Claim struct {
	ID        string  `json:"id"`
	EntityID  string  `json:"entity_id"`
	Predicate string  `json:"predicate"`
	Value     string  `json:"value"`
	Confidence float64 `json:"confidence"`
	Status    string  `json:"status"`
}

type ClaimListResponse struct {
	Data       []Claim    `json:"data"`
	Pagination Pagination `json:"pagination"`
}

func (c *Client) ListClaims(entityID string, cursor string, limit int) (*ClaimListResponse, error) {
	path := fmt.Sprintf("/claims?limit=%d", limit)
	if entityID != "" {
		path += "&entity_id=" + entityID
	}
	if cursor != "" {
		path += "&cursor=" + cursor
	}
	data, err := c.Get(path)
	if err != nil {
		return nil, err
	}
	var resp ClaimListResponse
	return &resp, json.Unmarshal(data, &resp)
}

func (c *Client) GetClaim(id string) ([]byte, error) {
	return c.Get("/claims/" + id)
}
