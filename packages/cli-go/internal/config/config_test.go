package config

import (
	"os"
	"path/filepath"
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

func TestLoad_FromYAMLFile(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "config.yaml")
	content := []byte("server_url: http://yaml-server:9999\nworkspace: ws-from-file\n")
	if err := os.WriteFile(cfgFile, content, 0o600); err != nil {
		t.Fatalf("write config file: %v", err)
	}

	// Override DefaultConfigPath by swapping the env; Load uses DefaultConfigPath internally,
	// but we'll test via the exported LoadFromPath helper.
	os.Unsetenv("ALAYA_SERVER_URL")
	os.Unsetenv("ALAYA_WORKSPACE")

	cfg, err := LoadFromPath(cfgFile)
	if err != nil {
		t.Fatalf("LoadFromPath() error: %v", err)
	}
	if cfg.ServerURL != "http://yaml-server:9999" {
		t.Errorf("expected ServerURL from file, got %q", cfg.ServerURL)
	}
	if cfg.Workspace != "ws-from-file" {
		t.Errorf("expected Workspace from file, got %q", cfg.Workspace)
	}
}

func TestLoad_EnvOverridesFile(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "config.yaml")
	content := []byte("server_url: http://yaml-server:9999\nworkspace: ws-from-file\n")
	if err := os.WriteFile(cfgFile, content, 0o600); err != nil {
		t.Fatalf("write config file: %v", err)
	}

	t.Setenv("ALAYA_SERVER_URL", "http://env-server:1111")
	t.Setenv("ALAYA_WORKSPACE", "ws-from-env")

	cfg, err := LoadFromPath(cfgFile)
	if err != nil {
		t.Fatalf("LoadFromPath() error: %v", err)
	}
	if cfg.ServerURL != "http://env-server:1111" {
		t.Errorf("env should override file, got %q", cfg.ServerURL)
	}
	if cfg.Workspace != "ws-from-env" {
		t.Errorf("env should override workspace, got %q", cfg.Workspace)
	}
}

func TestLoad_MissingFileUsesDefaults(t *testing.T) {
	os.Unsetenv("ALAYA_SERVER_URL")
	os.Unsetenv("ALAYA_WORKSPACE")

	cfg, err := LoadFromPath("/nonexistent/path/config.yaml")
	if err != nil {
		t.Fatalf("LoadFromPath() should not error on missing file, got: %v", err)
	}
	if cfg.ServerURL != "http://localhost:8000" {
		t.Errorf("expected default ServerURL, got %q", cfg.ServerURL)
	}
}

func TestLoad_PermissionDeniedReturnsError(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "config.yaml")
	if err := os.WriteFile(cfgFile, []byte("server_url: http://test\n"), 0o000); err != nil {
		t.Fatalf("write config file: %v", err)
	}
	// Skip on systems where root can read any file
	if os.Getuid() == 0 {
		t.Skip("running as root; permission check not applicable")
	}

	_, err := LoadFromPath(cfgFile)
	if err == nil {
		t.Fatal("expected error for permission denied, got nil")
	}
}

func TestLoad_InvalidYAMLReturnsError(t *testing.T) {
	dir := t.TempDir()
	cfgFile := filepath.Join(dir, "config.yaml")
	// Write invalid YAML
	if err := os.WriteFile(cfgFile, []byte(":\ninvalid: [unclosed\n"), 0o600); err != nil {
		t.Fatalf("write config file: %v", err)
	}

	_, err := LoadFromPath(cfgFile)
	if err == nil {
		t.Fatal("expected error for invalid YAML")
	}
}
