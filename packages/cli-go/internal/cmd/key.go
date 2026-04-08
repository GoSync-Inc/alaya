package cmd

import (
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var keyCmd = &cobra.Command{
	Use:   "key",
	Short: "Manage API keys",
}

var keyCreateCmd = &cobra.Command{
	Use:   "create",
	Short: "Create a new API key",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		data, err := c.Post("/api-keys", map[string]interface{}{
			"name":   "cli-generated",
			"scopes": []string{"read", "write"},
		})
		if err != nil {
			return err
		}
		if jsonOutput {
			fmt.Println(string(data))
			return nil
		}
		return output.PrintJSON(data)
	},
}

var keyListCmd = &cobra.Command{
	Use:   "list",
	Short: "List API keys",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		data, err := c.Get("/api-keys")
		if err != nil {
			return err
		}
		if jsonOutput {
			fmt.Println(string(data))
			return nil
		}
		return output.PrintJSON(data)
	},
}

var keyRevokeCmd = &cobra.Command{
	Use:   "revoke <prefix>",
	Short: "Revoke an API key",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		_, err = c.Delete("/api-keys/" + args[0])
		if err != nil {
			return err
		}
		fmt.Printf("API key %s revoked.\n", args[0])
		return nil
	},
}

func init() {
	rootCmd.AddCommand(keyCmd)
	keyCmd.AddCommand(keyCreateCmd, keyListCmd, keyRevokeCmd)
}
