package cmd

import (
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var workspaceCmd = &cobra.Command{
	Use:   "workspace",
	Short: "Manage workspaces",
}

var workspaceListCmd = &cobra.Command{
	Use:   "list",
	Short: "List workspaces",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		data, err := c.Get("/workspaces")
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

func init() {
	rootCmd.AddCommand(workspaceCmd)
	workspaceCmd.AddCommand(workspaceListCmd)
}
