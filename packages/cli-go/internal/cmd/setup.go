package cmd

import (
	"fmt"
	"strings"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/config"
	"github.com/spf13/cobra"
)

var setupProfile string

var setupCmd = &cobra.Command{
	Use:   "setup",
	Short: "Setup integrations",
}

var setupAgentCmd = &cobra.Command{
	Use:   "agent",
	Short: "Setup AI agent integration",
	RunE: func(cmd *cobra.Command, args []string) error {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		baseURL := cfg.ServerURL
		if serverURL != "" {
			baseURL = serverURL
		}
		apiKey, err := auth.GetAPIKey()
		if err != nil {
			return fmt.Errorf("authenticate first: alaya auth login")
		}
		switch strings.ToLower(setupProfile) {
		case "claude-code":
			fmt.Printf("# Add to .claude/settings.json:\n")
			fmt.Printf(`{"mcpServers":{"alaya":{"command":"alaya","args":["mcp"],"env":{"ALAYA_SERVER_URL":"%s","ALAYA_API_KEY":"%s"}}}}`, baseURL, apiKey)
			fmt.Println()
		case "codex":
			fmt.Printf("export ALAYA_SERVER_URL=%s\nexport ALAYA_API_KEY=%s\n", baseURL, apiKey)
		case "cursor":
			fmt.Printf("# Add to .cursor/mcp.json:\n")
			fmt.Printf(`{"mcpServers":{"alaya":{"command":"alaya","args":["mcp"],"env":{"ALAYA_SERVER_URL":"%s","ALAYA_API_KEY":"%s"}}}}`, baseURL, apiKey)
			fmt.Println()
		default:
			fmt.Printf("ALAYA_SERVER_URL=%s\nALAYA_API_KEY=%s\nALAYA_API_BASE=%s/api/v1\n", baseURL, apiKey, baseURL)
		}
		return nil
	},
}

func init() {
	rootCmd.AddCommand(setupCmd)
	setupCmd.AddCommand(setupAgentCmd)
	setupAgentCmd.Flags().StringVar(&setupProfile, "profile", "generic", "Agent profile (claude-code|codex|cursor|generic)")
}
