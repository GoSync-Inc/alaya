package client

import "encoding/json"

type SearchRequest struct {
	Query string `json:"query"`
	Limit int    `json:"limit,omitempty"`
}

type SearchResponse struct {
	Query        string         `json:"query"`
	Results      []EvidenceUnit `json:"results"`
	Total        int            `json:"total"`
	ChannelsUsed []string       `json:"channels_used"`
	ElapsedMs    int            `json:"elapsed_ms"`
}

type EvidenceUnit struct {
	SourceType string   `json:"source_type"`
	SourceID   string   `json:"source_id"`
	Content    string   `json:"content"`
	Score      float64  `json:"score"`
	Channels   []string `json:"channels"`
	EntityName *string  `json:"entity_name,omitempty"`
}

type AskRequest struct {
	Question   string `json:"question"`
	MaxResults int    `json:"max_results,omitempty"`
}

type AskResponse struct {
	Answer     string `json:"answer"`
	Answerable bool   `json:"answerable"`
	TokensUsed int    `json:"tokens_used"`
}

func (c *Client) Search(req SearchRequest) (*SearchResponse, error) {
	data, err := c.Post("/search", req)
	if err != nil {
		return nil, err
	}
	var resp SearchResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Ask(req AskRequest) (*AskResponse, error) {
	data, err := c.Post("/ask", req)
	if err != nil {
		return nil, err
	}
	var resp AskResponse
	if err := json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}
