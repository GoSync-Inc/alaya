package cmd

import (
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/config"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var searchLimit int

var searchCmd = &cobra.Command{
	Use:   "search [query]",
	Short: "Search corporate memory",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		query := args[0]

		cfg, err := config.Load()
		if err != nil {
			return fmt.Errorf("load config: %w", err)
		}

		baseURL := cfg.ServerURL
		if serverURL != "" {
			baseURL = serverURL
		}

		apiKey, err := auth.GetAPIKey()
		if err != nil {
			return err
		}

		c := client.New(baseURL, apiKey)
		resp, err := c.Search(client.SearchRequest{
			Query: query,
			Limit: searchLimit,
		})
		if err != nil {
			return err
		}

		return output.RenderSearch(resp, jsonOutput)
	},
}

func init() {
	searchCmd.Flags().IntVarP(&searchLimit, "limit", "n", 10, "Maximum number of results")
}
