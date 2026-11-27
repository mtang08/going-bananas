package main

import (
	"context"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/activityhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/checkinhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/checkins"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboardhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/goals"
	"github.com/mtang08/going-bananas/backend-go/internal/googlecalendar"
	"github.com/mtang08/going-bananas/backend-go/internal/httpapi"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"github.com/mtang08/going-bananas/backend-go/internal/planning"
	"github.com/mtang08/going-bananas/backend-go/internal/planninghttp"
	"github.com/mtang08/going-bananas/backend-go/internal/proposalhttp"
	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
	"github.com/mtang08/going-bananas/backend-go/internal/returnplan"
	"github.com/mtang08/going-bananas/backend-go/internal/travelhttp"
	"net/http"
	"path/filepath"
)

func applicationHandler(pool *pgxpool.Pool, mode api.AppMode, port, vitePort, root, privateDir string, dashboard http.Handler) http.Handler {
	travel := travelhttp.Handler{Pool: pool, Mode: string(mode), PrivateDir: privateDir, Provider: googlecalendar.New(privateDir)}
	review := proposalhttp.Handler{Store: drafts.Store{Pool: pool}, KBRoot: filepath.Join(root, "running_coach_kb"), Mode: string(mode)}
	activities := activityhttp.Handler{Pool: pool, Mode: string(mode)}
	weekly := httpapi.Weekly{Pool: pool, Mode: mode}
	registerReturnPlan := func(mux *http.ServeMux) {
		mux.Handle("GET /api/v1/running-interruption", returnplan.Handler{Pool: pool, Mode: string(mode)})
	}
	events := planninghttp.Handler{Pool: pool, Mode: string(mode)}
	calendarHTTP := calendarhttp.Handler{Pool: pool, Mode: string(mode)}
	checkinsHTTP := checkinhttp.Handler{Store: checkins.NewStore(pool, nil, refresh.Runs), Mode: string(mode)}
	registerChat := func(mux *http.ServeMux) {
		mux.Handle("/api/v1/coach/chat", dashboard)
		mux.Handle("/api/v1/coach/chat/", dashboard)
	}
	return httpapi.New(proposals.New(pool), goals.New(pool), planning.Reader{Pool: pool}, mode, port, vitePort, travel.Register, review.Register, weekly.Register, registerReturnPlan, activities.Register, calendarHTTP.Register, events.Register, checkinsHTTP.Register, registerChat)
}

func nativeDashboard(ctx context.Context, pool *pgxpool.Pool, mode api.AppMode, port, vitePort, root, privateDir string) (*coachdashboardhttp.Local, error) {
	return coachdashboardhttp.NewNative(ctx, pool, coachdashboardhttp.LocalConfig{Mode: string(mode), Port: port, VitePort: vitePort, RepoRoot: root, PrivateDir: privateDir})
}
