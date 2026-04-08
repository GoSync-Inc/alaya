package config

import (
	"os"
	"testing"
)

func TestLoad_Defaults(t *testing.T) {
	os.Unsetenv("ALAYA_SERVER_URL")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}
	if cfg.ServerURL != "http://localhost:8000" {
		t.Errorf("expected default ServerURL, got %q", cfg.ServerURL)
	}
}

func TestLoad_EnvOverride(t *testing.T) {
	t.Setenv("ALAYA_SERVER_URL", "http://example.com:9000")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error: %v", err)
	}
	if cfg.ServerURL != "http://example.com:9000" {
		t.Errorf("expected env ServerURL, got %q", cfg.ServerURL)
	}
}

func TestDefaultConfigPath(t *testing.T) {
	path := DefaultConfigPath()
	if path == "" {
		t.Error("DefaultConfigPath() returned empty string")
	}
	// Should contain .alaya/config.yaml
	if len(path) < len("/.alaya/config.yaml") {
		t.Errorf("path too short: %q", path)
	}
}
