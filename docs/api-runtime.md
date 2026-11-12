# Runtime API contract (analytics MVP)

All browser routes begin `/api/v1`. Every response uses `{schema_version:"v1",data_revision:number,mode:"demo"|"real"|"test",data:...}`. Error responses use `{error:{code,message,retryable,request_id,fields?}}`. Dates are `YYYY-MM-DD`, instants are ISO 8601 with offset, distances meters, durations seconds. Mutations require `Content-Type: application/json` and `X-Local-Request: 1`; same-origin Origin/Host checks apply. Query dates are inclusive local dates in profile timezone, maximum 366 days. Unspecified summary/history window is the last 28 local dates.

| Route | Request | `data` result |
|---|---|---|
| `GET /health/live`, `/health/ready` | — | `{status:"ok"|"unavailable",database?:boolean}` |
| `GET /profile` | — | `{version:number,timezone:string,cycle_anchor:string|null,anchor_confirmed:boolean,strength_days_confirmed:boolean,scheduled_strength_days:number[],facts:object,preferences:object,unknowns:string[]}`; version 0 is unset/default |
| `PUT /profile` | `{expected_version,timezone,cycle_anchor?,anchor_confirmed?,strength_days_confirmed?,scheduled_strength_days?,facts?,preferences?,unknowns?}` | profile object; version increments |
| `GET /activities?start_date=&end_date=&sport=&cursor=&limit=` | — | `{items:[activity],next_cursor:string|null,timezone,coverage:[...]}`; `activity` has `id,start_at,local_date,sport,subtype,distance_m,elapsed_s,moving_s,moving_pace_s_per_km,workout_label,resolution_state,source,provenance` |
| `GET /activities/{id}` | — | activity object with `annotations`, `sources`, `provenance` |
| `PATCH /activities/{id}/annotations` | `{expected_version,workout_label?,notes?,excluded?}` | detail activity |
| `GET /summary?as_of=&days=28` | — | `{as_of,timezone,metric_version:"analytics.v1",window:{start_date,end_date},current_week:{distance_m,run_count,missing_distance_count},rolling_7:{...},rolling_14:{...},selected:{distance_m,run_count,missing_distance_count,longest_elapsed_s,strength_count,strength_duration_s,strength_unknown_duration_count,low_impact_count,low_impact_duration_s,workout_distribution:{easy,quality,long,other,unknown}},weekly:[{start_date,end_date,distance_m,run_count,missing_distance_count,strength_count}],recent_runs:[activity],coverage:[...]}` |
| `GET /recovery?start_date=&end_date=` | — | `{timezone,series:{sleep:[{date,value,unit,statistic}],hrv:[...],resting_hr:[...]},trailing_7:{sleep:{mean,n,days},hrv:{...},resting_hr:{...}},coverage:[...]}`; no observation means no point |
| `GET /checkins?start_date=&end_date=&cursor=&limit=` | — | `{items:[checkin],next_cursor:string|null,truncated:boolean,timezone}`; checkin has `id,version,observed_at,recorded_at,symptoms,change,gait,feeling,effort,activity_id,note,associations:[{activity_id,kind,elapsed_hours,timing_uncertain,day_label}]}` |
| `POST /checkins` | `{idempotency_key,observed_at,symptoms,change?,gait,feeling,effort?,activity_id?,note?}` | checkin; 200 on key replay, 201 on create |
| `PATCH /checkins/{id}` | `{expected_version,observed_at?,symptoms?,change?,gait?,feeling?,effort?,activity_id?,note?}` | checkin, 409 on stale version |
| `GET /manual-sessions?start_date=&end_date=&cursor=&limit=` | — | `{items:[{id,version,date,time,kind,duration_s,effort,note,linked_activity_id}],next_cursor:string|null,truncated:boolean}` |
| `POST /manual-sessions` | `{date,time?,kind,duration_s?,effort?,note?}` | session |
| `PATCH /manual-sessions/{id}` | `{expected_version,date?,time?,kind?,duration_s?,effort?,note?,linked_activity_id?}` | session |
| `GET /plans?start_date=&end_date=` | — | `{items:[plan],opportunities:[{date,fortnight_index,slot}],unscheduled:boolean}`; plan has `id,version,status,start_date,end_date,profile_version,sessions:[{id,date,kind,target,completion_link_id,completion_activity_id,completion_manual_session_id}]` |
| `POST /plans` | `{start_date,end_date,sessions:[{date,kind,target?}]}` | draft plan |
| `POST /plans/{id}/accept`, `/reject` | `{expected_version,reason?}` | updated plan; acceptance validates anchor and 2 strength sessions per full week |
| `POST /completion-links` | `{planned_session_id,activity_id?,manual_session_id?}` | `{id,planned_session_id,activity_id,manual_session_id}` |
| `DELETE /completion-links/{id}` | `X-Local-Request: 1` | `{deleted:true}` |
| `GET /conflicts` | — | `{items:[{id,kind,status,activity_ids,manual_session_id,details}]}` |
| `POST /conflicts/{id}/resolve` | `{resolution:"merge"|"keep_separate"|"reverse",canonical_activity_id?}` | conflict |
| `GET /weekly-summary?week_start=` | — | `{week_start,week_end,timezone,metric_version,summary,plan_comparison:{planned,completed,unlinked,sessions},strength_coverage,recovery,missingness,checkins,plan,coverage,questions}` factual only |
| `POST /weekly-snapshots` | `{week_start}` | `{id,generated_at,data_revision,profile_version,plan_version,summary}` |
| `GET /weekly-snapshots` | — | `{items:[{id,week_start,week_end,generated_at,data_revision,profile_version,plan_version,stale,summary}]}` |
| `GET /context?as_of=&include_notes=false` | — | `{context_version:"coach_context.v1",generated_at,as_of,timezone,data_revision,profile_version,plan_version,profile,last_14_days,strength_coverage,prior_12_weeks,recent_activities,recent_manual_sessions,recovery,recent_checkins,next_14_days_plan,conflicts,omitted,metric_version}` |

Sync route implementation belongs to ingestion: `GET /sync/status`, `POST /sync`, `GET /sync/jobs/{id}`. Source tables are defined in `backend/app/models.py`; ingestion should use `backend/app/db.py` session helpers and `bump_revision(session)` after semantic changes.

Strength totals are observed counts only. When `profile.preferences.strength_source` is `strong`, summary, weekly recap, and context include `strength_coverage: {source:"strong",status:"unavailable",reason:"strong_not_connected",complete:false,observed_manual_count,observed_imported_count}` until a verified Strong source is connected. Unlinked planned strength means unknown completion, never an inferred skipped session. New accepted plans may replace an overlapping accepted plan only when their date ranges match exactly; otherwise acceptance returns `422 overlapping_plan`.


## Calendar and reviewed coaching API

Calendar authority enables `/calendar`, `/calendar/versions`, `/calendar/diff`,
`/calendar/edits`, `/calendar/rollback`, and explicit completion links. All source
writes serialize before app-state row locks. One successful source transaction
increments `data_revision` once and refreshes affected metrics/prompts atomically.
Derived-only reads do not increment the source revision.

- `GET /metrics/windows`: 7/14/28/56-day volume, effort, intensity and long-run
  metrics, plus spacing and symptom summaries.
- `GET /metrics/recovery?start=DATE&end=DATE`: inclusive dates, including missing
  nights; maximum92 dates.
- `GET /activities/UUID/execution`: actual, planned, completion, laps/steps,
  execution metrics, RPE and linked symptom facts.
- `GET /metrics/explain/UUID`: immutable stored metric evidence/configuration.
- `GET/POST /v2/checkins`, `PATCH /v2/checkins/UUID`, and subject RPE endpoints
  retain explicit unknowns and manual precedence.
- `GET /coach/v2/daily`: saved deterministic daily guidance.
- `GET /coach/proposals[?status=pending]` and `GET /coach/proposals/UUID`: saved
  changesets, before/after/current fields, source freshness and decisions.
- `POST /coach/proposals/UUID/decision`: explicit selection plus idempotency key
  and expected head. Full accepted/rejected partition required. Returns the
  stored decision result; source drift or changed terminal selection returns409.
  Invalid subsets return422 with structured field errors.

Snapshots and proposal submission use the local CLI, not HTTP endpoints.
Submission does not activate a plan. Terminal decisions are immutable; retries
with the identical selection return the original result before freshness checks.
The app keeps old read routes for source/history inspection while disabling old
planning writers after calendar cutover. Mode/origin protections apply throughout.
