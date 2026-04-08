package cmd

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/auth"
	"github.com/spf13/cobra"
)

var authCmd = &cobra.Command{
	Use:   "auth",
	Short: "Manage authentication",
}

var authLoginCmd = &cobra.Command{
	Use:   "login",
	Short: "Store an API key in the OS keyring",
	RunE: func(cmd *cobra.Command, args []string) error {
		fmt.Print("Enter API key: ")
		reader := bufio.NewReader(os.Stdin)
		key, err := reader.ReadString('\n')
		if err != nil {
			return fmt.Errorf("read API key: %w", err)
		}
		key = strings.TrimSpace(key)
		if key == "" {
			return fmt.Errorf("API key cannot be empty")
		}
		if err := auth.SetAPIKey(key); err != nil {
			return fmt.Errorf("store API key: %w", err)
		}
		fmt.Println("API key stored.")
		return nil
	},
}

var authLogoutCmd = &cobra.Command{
	Use:   "logout",
	Short: "Remove the stored API key",
	RunE: func(cmd *cobra.Command, args []string) error {
		if err := auth.DeleteAPIKey(); err != nil {
			return fmt.Errorf("delete API key: %w", err)
		}
		fmt.Println("API key removed.")
		return nil
	},
}

var authStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Show authentication status",
	RunE: func(cmd *cobra.Command, args []string) error {
		key, err := auth.GetAPIKey()
		if err != nil {
			fmt.Println("Not authenticated.")
			return nil
		}
		// Show only prefix for security
		prefix := key
		if len(key) > 8 {
			prefix = key[:8] + "..."
		}
		fmt.Printf("Authenticated (key prefix: %s)\n", prefix)
		return nil
	},
}

func init() {
	authCmd.AddCommand(authLoginCmd)
	authCmd.AddCommand(authLogoutCmd)
	authCmd.AddCommand(authStatusCmd)
}
