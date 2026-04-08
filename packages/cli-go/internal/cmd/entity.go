package cmd

import (
	"encoding/json"
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/config"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var entityCmd = &cobra.Command{
	Use:   "entity",
	Short: "Manage entities",
}

var entityListCmd = &cobra.Command{
	Use:   "list",
	Short: "List entities",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		resp, err := c.ListEntities(listCursor, listLimit)
		if err != nil {
			return err
		}
		if jsonOutput {
			return output.PrintJSON(resp)
		}
		for _, e := range resp.Data {
			fmt.Printf("%-36s  %s\n", e.ID, e.Name)
		}
		if resp.Pagination.HasMore && resp.Pagination.NextCursor != nil {
			fmt.Printf("\nMore results: --cursor %s\n", *resp.Pagination.NextCursor)
		}
		return nil
	},
}

var entityGetCmd = &cobra.Command{
	Use:   "get <id>",
	Short: "Get entity by ID",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		data, err := c.GetEntity(args[0])
		if err != nil {
			return err
		}
		if jsonOutput {
			fmt.Println(string(data))
			return nil
		}
		var result map[string]interface{}
		if err := json.Unmarshal(data, &result); err != nil {
			fmt.Println(string(data))
			return nil
		}
		if d, ok := result["data"]; ok {
			return output.PrintJSON(d)
		}
		return output.PrintJSON(result)
	},
}

var (
	listLimit  int
	listCursor string
)

func newClient() (*client.Client, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, fmt.Errorf("load config: %w", err)
	}
	baseURL := cfg.ServerURL
	if serverURL != "" {
		baseURL = serverURL
	}
	apiKey, err := auth.GetAPIKey()
	if err != nil {
		return nil, err
	}
	return client.New(baseURL, apiKey), nil
}

func init() {
	rootCmd.AddCommand(entityCmd)
	entityCmd.AddCommand(entityListCmd, entityGetCmd)
	entityListCmd.Flags().IntVar(&listLimit, "limit", 20, "Number of results")
	entityListCmd.Flags().StringVar(&listCursor, "cursor", "", "Pagination cursor")
}
