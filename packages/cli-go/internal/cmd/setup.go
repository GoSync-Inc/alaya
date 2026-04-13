package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/client"
	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/config"
	"github.com/spf13/cobra"
)

var setupProfile string
var setupShowSecret bool

const storedKeyPlaceholder = "<stored in keyring; rerun with --show-secret to print>"

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
			// No stored key — try creating one via bootstrap key
			bootstrapKey := os.Getenv("ALAYA_BOOTSTRAP_KEY")
			if bootstrapKey == "" {
				return fmt.Errorf("no API key found. Run 'alaya auth login' or set ALAYA_BOOTSTRAP_KEY to create one automatically")
			}
			fmt.Println("No API key found. Creating one via bootstrap key...")
			newKey, createErr := createAPIKeyViaBootstrap(baseURL, bootstrapKey)
			if createErr != nil {
				return fmt.Errorf("create API key: %w", createErr)
			}
			if storeErr := auth.SetAPIKey(newKey); storeErr != nil {
				return fmt.Errorf("store API key: %w", storeErr)
			}
			fmt.Println("API key created and stored.")
			apiKey = newKey
		}
		fmt.Print(renderAgentSetup(setupProfile, baseURL, apiKey, setupShowSecret))
		return nil
	},
}

func init() {
	rootCmd.AddCommand(setupCmd)
	setupCmd.AddCommand(setupAgentCmd)
	setupAgentCmd.Flags().StringVar(&setupProfile, "profile", "generic", "Agent profile (claude-code|codex|cursor|generic)")
	setupAgentCmd.Flags().BoolVar(&setupShowSecret, "show-secret", false, "Print the API key in generated output")
}

func renderAgentSetup(profile, baseURL, apiKey string, showSecret bool) string {
	renderedKey := storedKeyPlaceholder
	if showSecret {
		renderedKey = apiKey
	}

	switch strings.ToLower(profile) {
	case "claude-code":
		return fmt.Sprintf("# Add to .claude/settings.json:\n{\"mcpServers\":{\"alaya\":{\"command\":\"alaya\",\"args\":[\"mcp\"],\"env\":{\"ALAYA_SERVER_URL\":\"%s\",\"ALAYA_API_KEY\":\"%s\"}}}}\n", baseURL, renderedKey)
	case "codex":
		return fmt.Sprintf("export ALAYA_SERVER_URL=%s\nexport ALAYA_API_KEY=%s\n", baseURL, renderedKey)
	case "cursor":
		return fmt.Sprintf("# Add to .cursor/mcp.json:\n{\"mcpServers\":{\"alaya\":{\"command\":\"alaya\",\"args\":[\"mcp\"],\"env\":{\"ALAYA_SERVER_URL\":\"%s\",\"ALAYA_API_KEY\":\"%s\"}}}}\n", baseURL, renderedKey)
	default:
		return fmt.Sprintf("ALAYA_SERVER_URL=%s\nALAYA_API_KEY=%s\nALAYA_API_BASE=%s/api/v1\n", baseURL, renderedKey, baseURL)
	}
}

// createAPIKeyViaBootstrap calls POST /api-keys using the bootstrap key and returns the raw key.
func createAPIKeyViaBootstrap(baseURL, bootstrapKey string) (string, error) {
	c := client.New(baseURL, bootstrapKey)
	data, err := c.Post("/api-keys", map[string]interface{}{
		"name":   "cli-agent",
		"scopes": []string{"read", "write"},
	})
	if err != nil {
		return "", err
	}
	var resp struct {
		RawKey string `json:"raw_key"`
	}
	if err := json.Unmarshal(data, &resp); err != nil {
		return "", fmt.Errorf("parse key response: %w", err)
	}
	if resp.RawKey == "" {
		return "", fmt.Errorf("server did not return raw_key in response")
	}
	return resp.RawKey, nil
}
