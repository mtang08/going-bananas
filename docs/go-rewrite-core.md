# Workstream 1 · Application, training data and integration

The Go runtime registers all 81 HTTP operations verified during the port. The API supervisor and operational commands use Go in demo, test and real mode. Python remains available for offline historical Alembic upgrades and non-HTTP references. [Rewrite readiness](go-rewrite-readiness.md) · [Shared specification](go-backend-rewrite.md)

## Synthetic integration evidence

- Native calendar edits, completion, undo, links and decisions share the PostgreSQL writer lock. The source changes, rematches and required derived writes commit together. Focused comparisons cover retries, protected history, competing writers and rollback on a refresh failure. [Native self-report tests](../backend-go/internal/calendar/self_report_test.go) · [Transaction callbacks](#transaction-bound-metric-refresh)
- Native coaching exercised a full Sunday review through Chrome and the Vite proxy. The owner flow saved a pending draft, opened its review, accepted selected changes and advanced the calendar head once. Independent process tests exercised the helper and fake app-server through the actual API executable. [Coaching evidence](go-rewrite-coaching.md)
- Provider and phone check-in comparisons used synthetic PostgreSQL and loopback fixtures. Recovery checked native backup, restore into a fresh target, cold restart and retained receipts and IDs. Fresh databases bootstrap from the native SQL baseline. An older stamped database upgrades through Alembic. [Provider evidence](go-rewrite-providers.md) · [Operating procedure](operations.md)

## Real workspace deployment

Native demo seeding and same-day replay passed through the standard Make target. The integrated build, generated contract and schema drift checks, race suite, browser workflows and PostgreSQL comparisons passed. Schedule the real switch with the owner. Take and verify a current backup, stop the old supervisor and worker, and run the read-only `going-bananas workspace-preflight` against the selected workspace before startup refresh or worker writes. [Cutover and rollback](go-backend-rewrite.md#data-handoff-and-rollback)

### Planned-versus-actual assessment

Call `assessment.Refresh(ctx, tx, sessionUID, now)` inside the completion command's globally locked PostgreSQL transaction, after refreshing the linked activity's interval result. It reads the accepted plan, eligible actual, candidates and coverage; selects or restores the metric result by its source/dependency identity; and updates a derived completion status and data revision when it changes. The caller can roll back both the result and the enclosing completion change. The returned result ID is nil when the subject has disappeared. Unlinked self-reports retain their user-marked status.

```sh
(cd backend-go && go test -race ./internal/metrics/assessment ./internal/calendar)
```

The original comparison ran in independently migrated schemas and checked all stored metric columns except generated UUIDs. It separately verified stable row IDs on replay and restore, non-UTC session offsets, provenance for FIT, Strong and manual records, and caller rollback on a failing completion update. [Assessment transaction](../backend-go/internal/metrics/assessment/refresh.go) · [Native assessment package](../backend-go/internal/metrics/assessment)

### Transaction-bound metric refresh

Calendar decision handlers can pass `refresh.PlanMetrics(now, runs)` to `calendar.RefreshPlans` and `refresh.CompletionMetrics(now, runs)` to `calendar.DerivedRefresh`. The callbacks consume rematched IDs and persist affected activity, strength, plan, night and window results in the same transaction. A manual-only report recalculates its plan assessment and the applicable spacing windows. `assessment.RefreshBatch` increments the revision once when one or more derived statuses change.

Provider and check-in handlers can pass the Python-format scope strings and rematched IDs to `refresh.ScopeMetrics`. For recovery-only changes, request the current training day when its full window set is missing. `refresh.EnsureWindows` and `refresh.EnsureNights` provide the explicit local-date entry points. The activity callback covers session RPE, symptoms, long-run exposure, FIT intensity, intervals and aerobic efficiency. [Scope expansion](../backend-go/internal/metrics/refresh/scope.go) · [Calendar and window refresh](../backend-go/internal/metrics/refresh/refresh.go)

For a read-only dashboard transaction, `trainingwindows.CalculateActivity` computes session RPE, symptoms or long-run exposure. `metrics.Preview` formats an unstored result with its provenance and a null ID. The assessment PostgreSQL comparison exercises the read-only transaction and compares window, activity and scoped refresh output against Python. [Activity previews](../backend-go/internal/metrics/trainingwindows/preview.go) · [Result identity and storage](../backend-go/internal/metrics/result.go)
