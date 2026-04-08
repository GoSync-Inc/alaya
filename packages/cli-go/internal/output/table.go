package output

import (
	"fmt"
	"strings"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
)

func PrintSearchResults(resp *client.SearchResponse) {
	fmt.Printf("Query: %q — %d result(s) in %dms\n\n", resp.Query, resp.Total, resp.ElapsedMs)
	if len(resp.Results) == 0 {
		fmt.Println("No results found.")
		return
	}
	for i, r := range resp.Results {
		fmt.Printf("[%d] %.2f  %s\n", i+1, r.Score, r.SourceType)
		if r.EntityName != nil {
			fmt.Printf("    Entity: %s\n", *r.EntityName)
		}
		fmt.Printf("    %s\n", strings.TrimSpace(r.Content))
		fmt.Println()
	}
}

func PrintAskResponse(resp *client.AskResponse) {
	if !resp.Answerable {
		fmt.Println("(not enough information to answer)")
		return
	}
	fmt.Println(resp.Answer)
	fmt.Printf("\n[tokens used: %d]\n", resp.TokensUsed)
}
