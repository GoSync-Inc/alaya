package cmd

import (
	"encoding/json"
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var claimEntityID string

var claimCmd = &cobra.Command{
	Use:   "claim",
	Short: "Manage claims",
}

var claimListCmd = &cobra.Command{
	Use:   "list",
	Short: "List claims",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		resp, err := c.ListClaims(claimEntityID, listCursor, listLimit)
		if err != nil {
			return err
		}
		if jsonOutput {
			return output.PrintJSON(resp)
		}
		for _, cl := range resp.Data {
			fmt.Printf("%-36s  %s: %s (%.0f%%)\n", cl.ID, cl.Predicate, cl.Value, cl.Confidence*100)
		}
		return nil
	},
}

var claimGetCmd = &cobra.Command{
	Use:   "get <id>",
	Short: "Get claim by ID",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		data, err := c.GetClaim(args[0])
		if err != nil {
			return err
		}
		if jsonOutput {
			fmt.Println(string(data))
			return nil
		}
		var result map[string]interface{}
		json.Unmarshal(data, &result)
		return output.PrintJSON(result)
	},
}

func init() {
	rootCmd.AddCommand(claimCmd)
	claimCmd.AddCommand(claimListCmd, claimGetCmd)
	claimListCmd.Flags().StringVar(&claimEntityID, "entity-id", "", "Filter by entity ID")
}
