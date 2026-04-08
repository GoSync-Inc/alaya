package cmd

import (
	"github.com/spf13/cobra"
)

var (
	jsonOutput bool
	serverURL  string
	Version    = "dev"
)

var rootCmd = &cobra.Command{
	Use:     "alaya",
	Short:   "Alaya — corporate memory CLI",
	Long:    "Query corporate knowledge, manage entities, and configure AI agent access.",
	Version: Version,
}

func init() {
	rootCmd.PersistentFlags().BoolVar(&jsonOutput, "json", false, "Output in JSON format")
	rootCmd.PersistentFlags().StringVar(&serverURL, "server", "", "Server URL (overrides config)")
	rootCmd.AddCommand(authCmd)
	rootCmd.AddCommand(searchCmd)
	rootCmd.AddCommand(askCmd)
}

func Execute() error {
	return rootCmd.Execute()
}
