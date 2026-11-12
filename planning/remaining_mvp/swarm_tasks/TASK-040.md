# TASK-040 — Home page: today card, prompts, daily guidance, block card, 14-day strip


Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-A; wave 5 (dependency_graph.md).
Dependencies: TASK-039
File ownership: create `frontend/src/pages/Home.tsx`, `frontend/tests/home.test.tsx`
Forbidden changes: `App.tsx` (TASK-050 wires the page), `api.ts`, `api/types/*`, `styles.css` (TASK-050 adds the classes named here), all other pages. No proposal card (TASK-066 adds it in P0-B). No new dependency.

## Objective and observable end state
`<Home unit="mi" onCheckin={fn}/>` renders today's planned sessions, open prompts with actions, daily guidance or its empty state, the active block or its null state, and a 14-day strip (today … today+13) where provisional sessions carry class `certainty-provisional` and edited sessions show a "Changed" marker. Example: with the fixture below, the heading reads "Wednesday, November 11" and the today card shows "Easy run" and "30m".

## Inputs and fixed contracts
- Types, keys, helpers from `../api` (TASK-039): `CalendarView`, `SessionState`, `Completion`, `PromptList`, `Prompt`, `CheckinRequest`, `DailyGuidance`, `DECISION_LABELS`, `BlockVersion`, `Activity`, `Unit`, `MARKER_LABELS`, `qk`, `api`, `post`, `addDays`, `dateLabel`, `fmtDistance`, `fmtDuration`, `formatStep`, `sessionTitle`, `sessionMarker`, `invalidateKeys`, `fetchDailyGuidance`, `pageHref`, `ApiError`.
- Components: `QueryState` from `../components/QueryState` (props `{loading, error, stale, retry, children}` exactly as in the baseline `App.tsx`), `Empty` from `../components/Empty` (`{title, text}`). If either path does not exist after TASK-001, STOP.
- "Today" = `calendar.data.today` from the API (architecture §4). Never call `localDate()` in this file.
- Endpoints (schemas §3): `GET /calendar` (default range today−7…today+13), `GET /prompts`, `GET /coach/v2/daily` via `fetchDailyGuidance`, `GET /blocks/active` (data `BlockVersion | null`), `GET /activities/{id}` (existing), `POST /prompts/{id}/dismiss` (body `{}`).

## Implementation procedure
1. Create `frontend/src/pages/Home.tsx` exporting `export function Home({ unit, onCheckin }: { unit: Unit; onCheckin: (req: CheckinRequest) => void })`.
2. Queries (use `useQuery` / `useQueries` from `@tanstack/react-query` directly):
   - `calendar = useQuery({ queryKey: qk.calendarView('head'), queryFn: () => api<CalendarView>('/calendar') })`
   - `prompts = useQuery({ queryKey: qk.prompts, queryFn: () => api<PromptList>('/prompts') })`
   - `guidance = useQuery({ queryKey: qk.coachDaily, queryFn: fetchDailyGuidance })`
   - `block = useQuery({ queryKey: qk.blocksActive, queryFn: () => api<BlockVersion | null>('/blocks/active') })`
   - `open = prompts.data?.data.items.filter(p => p.status === 'open') ?? []`; `ids` = unique non-null `activity_id` of open prompts with kind `rpe` or `delayed_symptom`; `useQueries({ queries: ids.map(id => ({ queryKey: qk.activity(id), queryFn: () => api<Activity>(`/activities/${encodeURIComponent(id)}`) })) })`.
   - `dismiss = useMutation({ mutationFn: (id: string) => post<unknown>(`/prompts/${encodeURIComponent(id)}/dismiss`, {}), onSuccess: () => invalidateKeys(qc, [qk.prompts]) })`.
3. Layout inside `<section className="page-content home-page">`:
   - `page-heading`: eyebrow `TODAY`; `<h1>` = `dateLabel(today, {weekday:'long', month:'long', day:'numeric'})`, or `Today` while the calendar loads; `<p>` "Planned training, open prompts, and the next two weeks."; button `className="button primary"` text "Record check-in" → `onCheckin({kind:'exception', prompt:null, activityId:null})`.
   - Wrap the calendar-dependent parts in `<QueryState loading={calendar.isPending} error={calendar.error} stale={!!calendar.data} retry={() => calendar.refetch()}>`.
   - If `head === 0`: `<div className="notice warning">` containing `<strong>No calendar yet.</strong> Finish setup to fill the next 14 days. ` and `<a href={pageHref.settings}>Open setup</a>`. Skip the today card and the strip; still render prompts, guidance, block.
3b. Plan-end banner (D19, `prd.md` §6: no automatic roll-forward). When `head !== 0`: `last` = the maximum `local_date` over `calendar.data.sessions` (string compare). If `last` exists and `last <= addDays(today, 6)`, render `<div className="notice warning" role="status" data-testid="plan-end-banner">Plan ends on {dateLabel(last)} — run the weekly review</div>` above the today card. If `sessions` is empty, render the same element with text `No planned sessions — run the weekly review`. Otherwise render nothing. Days after `last` simply render empty in the strip (step 8); never synthesize sessions.
4. Today card `<div className="panel today-card" data-testid="today-card">`, `<h2>Today's plan</h2>`. Sessions with `local_date === today`, sorted by `slot`. Each row: `<strong>{sessionTitle(s)}</strong>`, intent, `fmtDuration(planned_duration_s)` only when not null, `fmtDistance(planned_distance_m, unit)` only when not null, one `<li>` per `formatStep(step, unit)` when `structure` is not null, certainty chip `<span className="status-chip">Committed|Provisional</span>`. If the session's `recipe_id` is null and `kind === 'run'` and not custom, add `<small>Effort-based until the first review picks a session.</small>`. No sessions → `<p>No session</p>` (exact text, `acceptance.md` §2.1).
5. Prompts panel `<div className="panel">`, `<h2>Prompts</h2>`, wrapped in its own `QueryState` for `prompts`. Each open prompt is `<div className="prompt-item" data-testid="prompt-item" data-kind={kind}>` with title, sub-text, and actions. Let `a` = the activity query result for `prompt.activity_id`, `s` = calendar session with `session_uid === prompt.session_uid`:
   - `rpe`: title `Rate your run` + (`a` ? ` on ${dateLabel(a.local_date)} · ${fmtDistance(a.distance_m, unit)}` : ''); sub "How hard was the entire session?"; button "Add RPE" → `onCheckin({kind:'post_run', prompt, activityId: prompt.activity_id})`.
   - `delayed_symptom`: title `Delayed-response check` + (`a` ? ` for your run on ${dateLabel(a.local_date)}` : ''); sub "Any pain or gait change since this run?"; button "Answer check" → `onCheckin({kind:'delayed_followup', prompt, activityId: prompt.activity_id})`.
   - `unmatched_session`: title "A run needs matching to a planned session"; sub "Pick the session on the Calendar page."; `<a href={pageHref.calendar}>Open calendar</a>`.
   - `missing_activity`: title `No activity found for ${s ? `${sessionTitle(s)} on ${dateLabel(s.local_date)}` : 'a planned session'}`; sub "Mark it skipped, moved, or not recorded on the Calendar page."; `<a href={pageHref.calendar}>Open calendar</a>`.
   - Every prompt also gets `<button className="text-button">Dismiss</button>` → `dismiss.mutate(prompt.id)`. Show `dismiss.error.message` in `<p className="error-text" role="alert">`.
   - Empty: `<p className="muted-text">No open prompts.</p>`.
6. Guidance panel `<div className="panel">`, `<h2>Daily guidance</h2>`, `QueryState` for `guidance`. `guidance.data === null` → `<p>No guidance today. Guidance appears after you record a check-in; without one, the planned session stands.</p>`. Otherwise: `<span className={`status-chip ${g.decision}`}>{DECISION_LABELS[g.decision]}</span>`, `<p>{g.rationale}</p>`; if `g.coach_review_suggested`: `<div className="notice warning">Coach review suggested. Run the running-coach skill (daily review) before training.</div>`; if `g.missing_inputs.length`: `<small>Missing inputs: {g.missing_inputs.map(statusText).join(', ')}</small>` (import `statusText`).
7. Block card `<div className="panel">`, `<h2>Training block</h2>`, `QueryState` for `block`. `null` → `<p>No active block. The calendar runs without one until the first block review.</p>`. Otherwise `<p>{b.objective}</p>` and `<small>Next review {dateLabel(b.review_date)}</small>`.
8. Strip `<div className="panel">`, `<h2>Next 14 days</h2>`, `<div className="strip-grid">` with 14 `<div className="strip-day" data-testid="strip-day" data-date={d}>` for `d = addDays(today, i)`, i = 0…13; add class `today` when `i === 0`. Day header: `dateLabel(d, {weekday:'short'})` and `d.slice(-2)`. For each session that day (sorted by slot): `<div className={`session-tag kind-${s.kind} certainty-${s.certainty}`} data-testid="session-tag">` containing `sessionTitle(s)`, then `<span className={`marker marker-${m}`}>{MARKER_LABELS[m]}</span>` where `m = sessionMarker(s, completionFor(s), today)`, then `<span className="marker marker-changed">Changed</span>` when `!s.is_original`. `completionFor(s)` = `completions.find(c => c.session_uid === s.session_uid)`. A day with no sessions shows `<span className="day-empty">No session</span>`.

## Tests and expected results
Create `frontend/tests/home.test.tsx`. Stub `fetch` with `vi.stubGlobal` exactly like `frontend/tests/app.test.tsx` (record `{url, method, body, headers}`; respond `{ok, status, json: async () => envelope}`; envelope `{schema_version:'v1', data_revision:1, mode:'demo', data}`). Render `<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><Home unit="mi" onCheckin={onCheckin}/></QueryClientProvider>` with `onCheckin = vi.fn()`.
Fixture `calendar`: `today:'2026-11-11'`, `head:2`, `version:2`, sessions: `s1` 2026-11-11 run REC001 committed `planned_duration_s:1800` is_original true; `s2` 2026-11-13 run `recipe_id:null custom:false placeholder:true` committed is_original false; `s3` 2026-11-19 run REC002 provisional is_original true; completions `[]`. Prompts: `p1` rpe `activity_id:'a1'`; `p2` delayed_symptom `activity_id:'a1'`. `/activities/a1` → `{id:'a1', local_date:'2026-11-10', distance_m:6437.376, sport:'running', ...}`. `/coach/v2/daily` → 200 null. `/blocks/active` → `null`.
Tests (`npx vitest run tests/home.test.tsx`, all pass):
1. "shows today and the strip": heading "Wednesday, November 11"; within `today-card`: "Easy run", "30m"; 14 elements with `data-testid="strip-day"`; the `session-tag` inside `[data-date="2026-11-19"]` has class `certainty-provisional`; `[data-date="2026-11-13"]` contains "Quality slot" and "Changed"; `[data-date="2026-11-11"]` contains "Planned".
2. "prompt actions open the right check-in": text "Rate your run on Nov 10 · 4.0 mi" appears; click "Add RPE" → `onCheckin` called with `{kind:'post_run', prompt: expect.objectContaining({id:'p1'}), activityId:'a1'}`; click "Answer check" → called with `kind:'delayed_followup'`.
3. "dismiss posts and refetches prompts": click the first "Dismiss" → a request `POST` to `/api/v1/prompts/p1/dismiss` with header `X-Local-Request: 1`; `/prompts` GET count becomes 2.
4. "no guidance and null block": "No guidance today." and "No active block." visible.
5. "guidance with coach review": `/coach/v2/daily` → `{decision:'modify', rationale:'Shorten today', coach_review_suggested:true, missing_inputs:[], ...}` → "Modify", "Shorten today", "Coach review suggested." visible.
6. "no calendar": `head:0`, `sessions:[]` → "No calendar yet." and a link with `href="#settings"` named "Open setup"; no `today-card`.
7. "plan-end banner": sessions only `s1` (2026-11-11) and `s2` (2026-11-13) → `plan-end-banner` text "Plan ends on Nov 13 — run the weekly review"; strip day `[data-date="2026-11-15"]` contains "No session". With the base fixture (last date 2026-11-19 > 2026-11-17) → no `plan-end-banner`.
8. "calendar error": `/calendar` → 500 `{error:{code:'request_failed',message:'boom'}}` → "Could not load this view" and "boom".

## Acceptance checklist
- [ ] `Home` exported with the exact props; no `localDate()` call in the file.
- [ ] Exact copy strings above; missing values render "missing", never 0.
- [ ] Only the listed endpoints and keys; dismiss invalidates `qk.prompts` only.
- [ ] `npx tsc --noEmit`, `npm run lint`, `npm test` pass.

## Completion report
Files; command outputs; blockers.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Planner-level details I fixed
Plan-end banner threshold today+6 per D19; strip covers today…today+13 only (past days live on the Calendar page); "Changed" = `is_original === false`, shown in addition to the completion marker; prompt titles use the activity date, not `opens_at`; the block card shows objective + review date only (TASK-066 adds the rest); copy strings.

## Canonical structure and completion contract
Import `flattenStructure` from api.ts and render expanded steps with key `${step_path}:${repeat_index ?? 'single'}`; no direct formatting of RepeatBlock. Fixtures use one repeat block with interleaved work/recovery, no per-step repeat property. Imported legacy_unstructured sessions display their preserved prescription and "Structured comparison unavailable"; do not call them quality placeholders. Completion status comes from the server for every linked subject; linking sends IDs/match method, never an invented completed_as_planned status. Move provenance remains visible; unknown comparison stays unknown.
