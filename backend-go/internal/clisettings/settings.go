// Package clisettings validates the workspace environment used by local commands.
package clisettings

import (
	"net/url"
	"os"
	"strings"
)

type validationError string

func (e validationError) Error() string { return string(e) }

type Settings struct {
	Mode       string
	DSN        string
	PrivateDir string
}

func Load() (Settings, error) {
	cfg := Settings{
		Mode:       getenv("APP_MODE", "demo"),
		DSN:        getenv("DATABASE_URL", "postgresql+psycopg://bananas:bananas@localhost:5432/bananas_demo"),
		PrivateDir: getenv("PRIVATE_DIR", "private"),
	}
	if cfg.Mode != "demo" && cfg.Mode != "real" && cfg.Mode != "test" {
		return Settings{}, validationError("APP_MODE must be demo, real, or test")
	}
	if !strings.HasPrefix(cfg.DSN, "postgresql+psycopg://") && !strings.HasPrefix(cfg.DSN, "postgresql://") {
		return Settings{}, validationError("Only PostgreSQL is supported")
	}
	cfg.DSN = strings.Replace(cfg.DSN, "postgresql+psycopg://", "postgresql://", 1)
	parsed, err := url.Parse(cfg.DSN)
	if err != nil {
		return Settings{}, validationError("invalid_database_url")
	}
	if parsed.Fragment != "" || !strings.HasSuffix(parsed.Path, "_"+cfg.Mode) {
		return Settings{}, validationError("Database name must end with APP_MODE suffix")
	}
	if cfg.PrivateDir == "" {
		cfg.PrivateDir = "."
	}
	return cfg, nil
}

func getenv(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return fallback
}
