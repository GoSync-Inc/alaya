package output

import (
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
)

func RenderSearch(resp *client.SearchResponse, asJSON bool) error {
	if asJSON {
		return PrintJSON(resp)
	}
	PrintSearchResults(resp)
	return nil
}

func RenderAsk(resp *client.AskResponse, asJSON bool) error {
	if asJSON {
		return PrintJSON(resp)
	}
	PrintAskResponse(resp)
	return nil
}
