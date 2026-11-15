# Frontend implementation map

Inherit the root iteration-speed policy. Change the smallest complete user flow;
reuse existing components and avoid introducing another UI or state framework.

Paths below are relative to `frontend/`.

| Concern | Entry point |
| --- | --- |
| Bootstrap, routing, navigation | `src/main.tsx`, `src/App.tsx` (hash routing; profile `planning_authority` chooses current/legacy views) |
| HTTP and wire types | `src/api.ts`, `src/api/types/` |
| Query helpers | `src/components/shared.ts`, `src/components/QueryState.tsx` |
| Current athlete loop | `src/pages/Home.tsx`, `Calendar.tsx`, `ProposalReview.tsx`, `CheckinModalV2.tsx` |
| Blocks/configuration | `src/pages/Block.tsx`, `PlanningSettings.tsx`, `Settings.tsx` |
| Analytics/history | `src/pages/Trends.tsx`, `Activity.tsx`, `History.tsx`, `Strength.tsx` |
| Legacy views | `src/pages/Overview.tsx`, `Cycle.tsx`, `Coach.tsx`, `CheckinModal.tsx`, `src/PlanViews.tsx` |
| Shared domain visuals | `src/components/`: workout structure, plan overview, weekly mileage, activity/recovery |
| UI primitives and theme | `src/components/ui/`, `src/components/Modal.tsx`, `src/theme.css`, `src/styles.css` |

Use React Query for server state and the shared API client for envelopes, errors,
and local-request headers. Invalidate affected queries after mutations. Treat
server validation and current revisions as authoritative; changing a draft must
not leave selections bound to its previous revision.

Use local shadcn/Radix primitives, Tailwind v4 semantic tokens, and the existing
Modal for focus/Escape behavior. Read [the UI guide](../docs/ui-system.md) for
component changes. Keep feature CSS local and avoid broad global control styles.
Preserve style layer ordering in `main.tsx`. Format touched files, not the repo.

Show loading, error, missing, provisional, pending, and accepted states accurately.
Use real labels and keyboard-accessible controls. Unknown values must not display
as zero or healthy. Pending proposals must not appear to be accepted workouts or
contribute to accepted-plan forecasts. User-facing copy explains training/actions;
protocol IDs and implementation details belong in diagnostics.

Tests live in `tests/`; Playwright specs live in root `e2e/` and use
`playwright.config.ts`. From `frontend/`, use `npm test -- tests/proposals.test.tsx`
(choose the relevant file), `npm run lint`, and `npm run build` (includes TypeScript
build checks). For broad UI changes, run the full frontend tests and inspect
desktop/mobile layout and keyboard behavior. Browser mutations use a demo app;
real-app inspection stays read-only. See root README for browser setup.

When changing coaching instructions shown to the athlete, keep `src/pages/Guide.tsx`
and [docs/user-guide.md](../docs/user-guide.md) consistent with the current skill.
