package client

func (c *Client) GetTree(path string) ([]byte, error) {
	if path == "" {
		return c.Get("/tree")
	}
	return c.Get("/tree/" + path)
}

func (c *Client) ExportTree(path string) ([]byte, error) {
	return c.Post("/tree/export", map[string]string{"path": path})
}
