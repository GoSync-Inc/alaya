package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

type Config struct {
	ServerURL string `yaml:"server_url"`
	Workspace string `yaml:"workspace"`
}

func DefaultConfigPath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".alaya", "config.yaml")
}

// Load reads config from the default path (~/.alaya/config.yaml) then applies env overrides.
func Load() (*Config, error) {
	return LoadFromPath(DefaultConfigPath())
}

// LoadFromPath reads config from the given path then applies env overrides.
// A missing file is not an error — defaults are used instead.
func LoadFromPath(path string) (*Config, error) {
	cfg := &Config{
		ServerURL: "http://localhost:8000",
	}

	data, err := os.ReadFile(path)
	if err == nil {
		if err := yaml.Unmarshal(data, cfg); err != nil {
			return nil, fmt.Errorf("parse config: %w", err)
		}
	}
	// file not found is acceptable — continue with defaults

	// Env vars take priority over file settings
	if url := os.Getenv("ALAYA_SERVER_URL"); url != "" {
		cfg.ServerURL = url
	}
	if ws := os.Getenv("ALAYA_WORKSPACE"); ws != "" {
		cfg.Workspace = ws
	}

	return cfg, nil
}
