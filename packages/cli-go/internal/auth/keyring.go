package auth

import (
	"fmt"
	"os"

	"github.com/zalando/go-keyring"
)

const serviceName = "alaya-cli"

func GetAPIKey() (string, error) {
	// Env takes priority
	if key := os.Getenv("ALAYA_API_KEY"); key != "" {
		return key, nil
	}
	key, err := keyring.Get(serviceName, "api_key")
	if err != nil {
		return "", fmt.Errorf("no API key found: run 'alaya auth login' or set ALAYA_API_KEY")
	}
	return key, nil
}

func SetAPIKey(key string) error {
	return keyring.Set(serviceName, "api_key", key)
}

func DeleteAPIKey() error {
	return keyring.Delete(serviceName, "api_key")
}
