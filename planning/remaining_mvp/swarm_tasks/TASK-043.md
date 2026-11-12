# TASK-043 — Trends page: volume, long-run exposure, sRPE load, intensity time, hard-session spacing, recovery

Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-A; wave 5 (dependency_graph.md).
Dependencies: TASK-039
File ownership: create `frontend/src/pages/Trends.tsx`, `frontend/tests/trends.test.tsx`
Forbidden changes: `App.tsx`, `api.ts`, `api/types/*`, `styles.css`, other pages (the old Overview page stays untouched; TASK-050 removes it from navigation). No composite/readiness score, no ACWR (E6). Charts: `recharts` only. No new dependency.

## Objective and observable end state
`<Trends unit="mi"/>` shows the P0 metrics for a selectable rolling window (7/14/28/56 days, default 28) from `GET /metrics/windows`, the 14-day hard-session sequence, and a 28-night recovery table + chart from `GET /metrics/recovery`. Every absent value reads "missing" (or its status text); intensity without anchors reads "No anchor …". Example: 28-day volume 16,093.44 m / 5 runs / 9,000 s renders "10.0 mi" and "5 runs · 2h 30m timer time".

## Inputs and fixed contracts
- From `../api` (TASK-039): `MetricWindows`, `WindowMetrics`, `ZoneDistribution`, `RecoveryNights`, `RecoveryNight`, `RecoverySignal`, `HardClass`, `Unit`, `qk`, `api`, `query`, `addDays`, `dateLabel`, `fmtDistance`, `fmtDuration`, `fmtPercent`, `statusText`, `MISSING`. `QueryState` from `../components/QueryState` (STOP if missing).
- `metrics.md` §2 windows (7/14/28/56 in UI; 84 is block-only), §3 (3 zones per modality, never blended), §4 parameters; E6/E7. Server supplies "today" as `as_of`; never call `localDate()`.
- Queries: `windows = useQuery({queryKey: qk.metricsWindows, queryFn: () => api<MetricWindows>('/metrics/windows')})`; with `asOf = windows.data?.data.as_of`, `start = addDays(asOf,-27)`, `end = asOf`: `recovery = useQuery({queryKey: qk.metricsRecovery(start,end), enabled: !!asOf, queryFn: () => api<RecoveryNights>(`/metrics/recovery${query({start, end})}`)})`. Read-only page: no mutations.

## Implementation procedure
1. Export `export function Trends({ unit }: { unit: Unit })`; state `days: 7 | 14 | 28 | 56` (default 28). `w = windows.data?.data.windows.find(x => x.days === days) ?? null`.
2. Heading: eyebrow `TRENDS`; `<h1>Trends.</h1>`; `<p>Rolling totals and signals. Missing data is shown as missing, never as zero.</p>`. Toolbar `<div className="segmented" aria-label="Trend window">` with buttons "7 days", "14 days", "28 days", "56 days" (`className={days === n ? 'active' : ''}`). Wrap content in `QueryState` for `windows`.
3. `<div className="trend-grid">` with panels; each panel has `<h2>` and a `data-testid`. A null result → `${Title}: missing`; a result with `value === null` → `${Title}: ${statusText(status)}` + (` (${reason_codes.join(', ')})` when non-empty). When `quality_status` is `limited` or `insufficient`, add `<small>Data coverage: {quality_status}</small>`.
   - **Running volume** (`trend-volume`, Title "Volume"): `<strong>{fmtDistance(distance_m, unit)}</strong>`; `<p>{run_count} {run_count === 1 ? 'run' : 'runs'} · {fmtDuration(timer_duration_s)} timer time</p>`; `previous` → `Previous ${days} days: ${fmtDistance(p.distance_m, unit)} · ${p.run_count} ${p.run_count === 1 ? 'run' : 'runs'}`, null → "Previous window: missing".
   - **Long-run exposure** (`trend-long-run`, Title "Long-run exposure"): `latest === null` → "No long run in this window."; else lines `Latest long run ${dateLabel(l.local_date)} · ${fmtDuration(l.timer_s)} · ${fmtDistance(l.distance_m, unit)}`; `Vs recent max: duration ${fmtPercent(l.duration_ratio_to_recent_max)} · distance ${fmtPercent(l.distance_ratio_to_recent_max)}`; `Share of 7-day running: ${fmtPercent(l.weekly_share_duration)}`; `Classified from ${SRC[l.classification_source]} (${l.classification_confidence} confidence)` with `SRC = {plan_link:'the plan', manual:'your label', long_rule:'the duration rule'}`; `Delayed symptoms: ${DS[l.delayed_symptom_status]}` with `DS = {reported:'reported', none_reported:'none reported', unknown:'unknown (no follow-up)'}`; then `${long_run_count} long ${long_run_count === 1 ? 'run' : 'runs'} in ${days} days`.
   - **Session RPE load** (`trend-srpe`, Title "Session RPE load"): `<strong>{load_au == null ? MISSING : `${Math.round(load_au)} AU`}</strong>`; `RPE on ${sessions_with_rpe} of ${sessions_total} runs`; `Duration coverage ${fmtPercent(coverage_duration)}`; `<small>Runs without RPE are left out, not estimated.</small>`.
   - **Intensity time** (`trend-intensity`, Title "Intensity"): for `[['hr','Heart rate','intensity-hr'], ['speed','Pace','intensity-speed']]` render `<p data-testid={id}>` with: status `available`/`partial` → `${label}: Easy ${fmtDuration(easy_s)} · Moderate ${fmtDuration(moderate_s)} · High ${fmtDuration(high_s)} · Unknown ${fmtDuration(unknown_s)} · Coverage ${fmtPercent(coverage)}` + (` · low-confidence anchor` when `confidence === 'low'`); `reason_codes.includes('ANCHOR_MISSING')` → `${label}: No anchor — add aerobic-upper and threshold-lower anchors in Settings.`; otherwise `${label}: ${statusText(status)}` + reasons as above.
   - **Hard-session spacing** (`trend-spacing`, Title "Hard-session spacing"; uses `windows.data.data.spacing`, independent of `days`): `<small>Rolling 14-day calendar</small>`; `sequence` empty → "No hard sessions in the 14-day calendar."; else `<ol>` of `${dateLabel(local_date)} · ${CL[class]}`; then `<ul>` of gaps `${CL[from_class]} → ${CL[to_class]}: ${hours}` + (` (low confidence)` when `confidence === 'low'`), where `hours` = both null → `MISSING`; `hours_min === hours_max` (or one null) → `${Math.round(the non-null value)} h`; else `${Math.round(hours_min)}–${Math.round(hours_max)} h`. `CL = {quality:'Quality', long:'Long run', lower_body_strength:'Lower-body strength'}`.
4. Recovery panel `<div className="panel" data-testid="trend-recovery">`, `<h2>Recovery</h2>`, `<p>Sleep, overnight HRV, and resting HR per night. Missing nights stay missing.</p>`, own `QueryState` for `recovery`.
   - Chart: `<div className="chart" role="img" aria-label="Overnight HRV and resting HR by night"><ResponsiveContainer width="100%" height={220}><LineChart data={nights.map(n => ({date: n.local_date, hrv: n.hrv.value, rhr: n.resting_hr.value}))}><CartesianGrid vertical={false} stroke="#e9e7df"/><XAxis dataKey="date" tickFormatter={x => dateLabel(x)} fontSize={11}/><YAxis fontSize={11}/><Tooltip/><Line dataKey="hrv" name="HRV (ms)" stroke="#5b754d" dot={false} connectNulls={false}/><Line dataKey="rhr" name="Resting HR (bpm)" stroke="#9b704c" dot={false} connectNulls={false}/></LineChart></ResponsiveContainer></div>`.
   - Table `<table aria-label="Recovery nights">` columns "Night", "Sleep", "HRV", "Resting HR", "Baseline", "Flags"; rows newest first, `<tr data-testid="recovery-night" data-date={local_date} className={allMissing ? 'recovery-night missing' : 'recovery-night'}>` (`allMissing` = all three signals have `status === 'missing'`). Cells: `dateLabel(local_date, {weekday:'short', month:'short', day:'numeric'})`; sleep `value != null ? fmtDuration(value) : statusText(status)`; HRV `value != null ? `${Math.round(value)} ms` : statusText(status)`; resting HR `value != null ? `${Math.round(value)} bpm` : statusText(status)`; baseline from `hrv.baseline_state`: `none`→"No baseline", `provisional`→"Provisional", `established`→"Established"; flags joined by ", " from: `hrv.adverse`→"Low HRV", `resting_hr.adverse`→"High resting HR", `sleep.adverse`→"Short sleep", `subjective_poor`→"Poor subjective", `discordance`→"Signals disagree"; none → "None".
   - `nights` empty → "No recovery nights in this range." (never a zero row).

## Tests and expected results
Create `frontend/tests/trends.test.tsx`. Copy the `vi.mock('recharts', …)` block from `frontend/tests/app.test.tsx` (add `Line`, `LineChart`, `Tooltip`, `CartesianGrid`, `XAxis`, `YAxis` stubs). Fetch stub pattern as in that file; `retry:false`; `unit="mi"`.
Fixture `/metrics/windows`: `as_of:'2026-11-11'`; window 28: volume value `{distance_m:16093.44, run_count:5, timer_duration_s:9000, previous:{distance_m:8046.72, run_count:3, timer_duration_s:5400}}`; long_run value `{long_run_count:1, latest:{local_date:'2026-11-09', timer_s:4800, distance_m:13440, duration_ratio_to_recent_max:1.12, distance_ratio_to_recent_max:1.1, weekly_share_duration:0.4, weekly_share_distance:0.41, classification_source:'plan_link', classification_confidence:'high', delayed_symptom_status:'unknown', activity_id:'a2'}}`; srpe value `{load_au:420, sessions_with_rpe:2, sessions_total:5, coverage_duration:0.31, coverage_sessions:0.4}`; intensity value with `hr` and `speed` `{status:'not_assessable', reason_codes:['ANCHOR_MISSING'], …nulls}`. Window 7: all four results `null`. `spacing` value `{sequence:[{class:'quality', local_date:'2026-11-05', …}, {class:'long', local_date:'2026-11-09', …}], gaps:[{from_class:'quality', to_class:'long', hours_min:96, hours_max:96, confidence:'high', …}]}`. `/metrics/recovery`: nights `2026-11-07` (all three `{status:'missing', value:null, baseline_state:'established', valid_nights:30, z:null, adverse:null}`), `2026-11-08` (sleep 25200, hrv 60, resting_hr 52, all `available`, `established`, `adverse:false`; `subjective_poor:false`, `discordance:false`).
Tests (`npx vitest run tests/trends.test.tsx`):
1. "28-day volume": "10.0 mi"; "5 runs · 2h 30m timer time"; "Previous 28 days: 5.0 mi · 3 runs".
2. "window switch keeps missing explicit": click "7 days" → "Volume: missing", "Session RPE load: missing"; no "0.0 mi".
3. "intensity without anchors": `getByTestId('intensity-hr')` text "Heart rate: No anchor — add aerobic-upper and threshold-lower anchors in Settings."
4. "intensity with anchors": hr `{status:'available', easy_s:5400, moderate_s:600, high_s:0, unknown_s:60, coverage:0.95, confidence:'moderate', …}` → "Heart rate: Easy 1h 30m · Moderate 10m · High 0m · Unknown 1m · Coverage 95%".
5. "sRPE": "420 AU", "RPE on 2 of 5 runs", "Duration coverage 31%".
6. "long run": "Latest long run Nov 9 · 1h 20m · 8.4 mi" and "Delayed symptoms: unknown (no follow-up)".
7. "spacing": "Quality → Long run: 96 h".
8. "recovery missing nights": row `[data-date="2026-11-07"]` has class `missing` and contains "missing" three times; row 2026-11-08 contains "7h 00m", "60 ms", "52 bpm", "Established", "None".
9. "recovery range from server today": a GET URL contains `/metrics/recovery?start=2026-10-15&end=2026-11-11`.
10. "error": `/metrics/windows` → 500 → "Could not load this view".

## Acceptance checklist
- [ ] Exact copy above; missing never rendered as 0; HR and pace distributions never combined.
- [ ] Only the two GET endpoints and the listed keys; no mutation.
- [ ] `npx tsc --noEmit`, `npm run lint`, `npm test` pass.

## Completion report
Files; command outputs; blockers.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Planner-level details I fixed
Default window 28 days; recovery range = server today − 27 … today; one chart (HRV + RHR, gaps not connected); baseline column shows the HRV baseline state; flag wording; computed zeros (e.g. `high_s: 0`) render as `0m` because they are measured, while nulls render `missing`.
