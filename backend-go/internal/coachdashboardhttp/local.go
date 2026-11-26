package coachdashboardhttp

import (
	"context"
	"errors"
	"net/http"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

type LocalConfig struct {
	RepoRoot, PrivateDir, Mode, Port, VitePort string
}

type Local struct {
	http.Handler
	gateway *coachdashboard.Gateway
	auth    *coachdashboard.Auth
}

// NewLocal imports the configured mode's file conversation before serving it.
// The owner supplies the migrated pool and transactional domain tool handlers.
func NewLocal(ctx context.Context, pool *pgxpool.Pool, cfg LocalConfig, tools coachdashboard.ToolHandlers) (*Local, error) {
	if pool == nil || cfg.RepoRoot == "" || cfg.PrivateDir == "" || cfg.Port == "" || cfg.VitePort == "" {
		return nil, errors.New("incomplete dashboard server configuration")
	}
	launcher, err := coachdashboard.NewLocalLauncher(cfg.RepoRoot, cfg.Mode)
	if err != nil {
		return nil, err
	}
	store := coachdashboard.NewStore(pool, cfg.Mode)
	if err := store.ImportPythonFiles(ctx, cfg.PrivateDir); err != nil {
		return nil, err
	}
	transport := &coachdashboard.StdioAppServer{Open: launcher.Open, Workspace: launcher.Workspace(), LoadInstructions: func() (string, error) { return coachdashboard.LoadInstructions(cfg.RepoRoot) }, Tools: coachdashboard.NewDashboardTools(store, tools)}
	auth := coachdashboard.NewAuth(launcher.Open)
	gateway := coachdashboard.NewGateway(store, transport, auth)
	h := NewWithAuth(gateway, PostgresMetadata{Pool: pool}, auth, cfg.Mode, cfg.Port, cfg.VitePort)
	return &Local{Handler: h, gateway: gateway, auth: auth}, nil
}

// Shutdown drains the current conversation and any explicit login attempt.
func (l *Local) Shutdown(ctx context.Context) error {
	turnErr := l.gateway.Shutdown(ctx)
	_, authErr := l.auth.Cancel(ctx)
	return errors.Join(turnErr, authErr)
}
