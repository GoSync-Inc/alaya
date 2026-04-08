package cmd

import (
	"fmt"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var treeCmd = &cobra.Command{
	Use:   "tree",
	Short: "Knowledge tree",
}

var treeShowCmd = &cobra.Command{
	Use:   "show [path]",
	Short: "Show tree node",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		path := ""
		if len(args) > 0 {
			path = args[0]
		}
		data, err := c.GetTree(path)
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

var treeExportCmd = &cobra.Command{
	Use:   "export [path]",
	Short: "Export subtree as markdown",
	RunE: func(cmd *cobra.Command, args []string) error {
		c, err := newClient()
		if err != nil {
			return err
		}
		path := ""
		if len(args) > 0 {
			path = args[0]
		}
		data, err := c.ExportTree(path)
		if err != nil {
			return err
		}
		fmt.Println(string(data))
		return nil
	},
}

func init() {
	rootCmd.AddCommand(treeCmd)
	treeCmd.AddCommand(treeShowCmd, treeExportCmd)
}
