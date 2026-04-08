package cmd

import (
	"fmt"
	"os"

	"github.com/GoSync-Inc/alaya/packages/cli-go/internal/output"
	"github.com/spf13/cobra"
)

var ingestSourceType string

var ingestCmd = &cobra.Command{
	Use:   "ingest",
	Short: "Ingest data into Alaya",
}

var ingestFileCmd = &cobra.Command{
	Use:   "file <path>",
	Short: "Ingest file content",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		content, err := os.ReadFile(args[0])
		if err != nil {
			return fmt.Errorf("read file: %w", err)
		}
		return doIngest(string(content), ingestSourceType)
	},
}

var ingestTextCmd = &cobra.Command{
	Use:   "text <content>",
	Short: "Ingest text content",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return doIngest(args[0], ingestSourceType)
	},
}

func doIngest(content, sourceType string) error {
	c, err := newClient()
	if err != nil {
		return err
	}
	body := map[string]string{
		"content":     content,
		"source_type": sourceType,
	}
	data, err := c.Post("/ingest", body)
	if err != nil {
		return err
	}
	if jsonOutput {
		fmt.Println(string(data))
		return nil
	}
	return output.PrintJSON(data)
}

func init() {
	rootCmd.AddCommand(ingestCmd)
	ingestCmd.AddCommand(ingestFileCmd, ingestTextCmd)
	ingestFileCmd.Flags().StringVar(&ingestSourceType, "source-type", "document", "Source type")
	ingestTextCmd.Flags().StringVar(&ingestSourceType, "source-type", "manual", "Source type")
}
