package config

import (
	"os"
	"path/filepath"
)

type Config struct {
	ServerURL string `yaml:"server_url"`
	Workspace string `yaml:"workspace"`
}

func DefaultConfigPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".alaya", "config.yaml")
}

func Load() (*Config, error) {
	cfg := &Config{
		ServerURL: "http://localhost:8000",
	}
	// Env override
	if url := os.Getenv("ALAYA_SERVER_URL"); url != "" {
		cfg.ServerURL = url
	}
	return cfg, nil
}
