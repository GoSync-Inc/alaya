package cmd

import (
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/config"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var askMaxResults int

var askCmd = &cobra.Command{
	Use:   "ask [question]",
	Short: "Ask a natural language question",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		question := args[0]

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
		resp, err := c.Ask(client.AskRequest{
			Question:   question,
			MaxResults: askMaxResults,
		})
		if err != nil {
			return err
		}

		return output.RenderAsk(resp, jsonOutput)
	},
}

func init() {
	askCmd.Flags().IntVarP(&askMaxResults, "max-results", "n", 5, "Maximum number of evidence results to use")
}
