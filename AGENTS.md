# Going Bananas: agent working agreement

## Optimize for iteration speed

This is a private, local app with one user: its owner and athlete. **Iteration
speed and useful end-to-end features are the highest engineering priorities.**

- Make reasonable implementation decisions and carry authorized work through to
  completion. Ask only when a missing decision materially changes the outcome.
- Breaking APIs, schemas, internal interfaces, and UI flows is acceptable. Update
  their consumers together. Do not add compatibility layers, deprecation periods,
  feature flags, or rollout machinery solely to preserve old behavior.
- Temporary broken builds, failing tests, and incomplete app states are acceptable
  during implementation and between related features, provided there is a clear
  plan to finish the full feature. Before a disruptive change, identify the target
  behavior, affected layers, remaining steps, and how completion will be verified.
  Keep this lightweight; a short task plan usually suffices.
- If work spans sessions, leave a concise handoff with what is broken, the next
  concrete steps, and the completion check. Do not call an unfinished feature done.
- Prefer direct code, existing dependencies, and complete vertical slices. Avoid
  speculative abstractions, enterprise infrastructure, and unrelated cleanup.
- Validate the behavior that changed. Use focused checks while iterating; broaden
  at integration boundaries. Documentation-only edits need link/content checks,
  not the entire application suite. Do not add tests that merely mirror code.
- Preserve unrelated user work. Permission to break software contracts is not
  permission to lose the athlete's real history, expose secrets, or fabricate data.

## Start here; load only what the task needs

Read the relevant directory's `AGENTS.md`, then open the entry points below.
Search for a specific symbol or endpoint with `rg`; avoid reading every document,
all migrations, the full research library, or private data to orient yourself.

| Task | First files to inspect |
| --- | --- |
| Athlete coaching | [.codex/skills/going-bananas-coach/SKILL.md](.codex/skills/going-bananas-coach/SKILL.md), then its selected workflow/reference |
| Coaching snapshots, validation, proposals | `backend/app/api/coach.py`, `backend/app/services/{snapshot,decision_inputs,proposals}.py` |
| Calendar, completion, undo | `backend/app/api/calendar.py`, `backend/app/services/{calendar,matching,weekly_digest}.py` |
| Blocks, anchors, schedule configuration | `backend/app/api/{planning,anchors}.py`, `backend/app/planning_models.py` |
| Check-ins and daily guidance | `backend/app/api/checkins.py`, `backend/app/services/{checkins,prompts,daily_guidance}.py` |
| Metrics, FIT, weekly mileage | `backend/app/metrics/`, `backend/app/services/{fit_ingest,weekly_projection}.py` |
| Garmin/Strong ingestion | `backend/app/adapters/`, `backend/app/services/{sync,export_import,strong_import}.py` |
| UI and navigation | [frontend/AGENTS.md](frontend/AGENTS.md), `frontend/src/App.tsx`, relevant `src/pages/` file |
| Research content/retrieval | [running_coach_kb/AGENTS.md](running_coach_kb/AGENTS.md), `backend/app/services/knowledge.py` |
| Startup, modes, backups | `Makefile`, `scripts/serve.py`, `scripts/with-mode`, [docs/operations.md](docs/operations.md) |
| Save an idea for later | `.codex/skills/going-bananas-feature-request/SKILL.md`, `docs/backlog.md` |

The architecture is React/TypeScript/Vite → same-origin FastAPI `/api/v1` →
SQLAlchemy/PostgreSQL, plus local import/sync workers. Codex supplies coaching
reasoning through the skill/helper; ordinary app requests, metrics, imports, and
calendar expansion do not call a model. Strong remains the lifting workflow.

## Current versus historical contracts

The current coaching path is the **repo-local `.codex/skills/going-bananas-coach`**
package and the calendar proposal API. Its manifest declares `coach_proposal.v1`,
calendar authority, and manual activation. `README.md` describes this user flow.
The `skills/going-bananas-coach/` package and `api/agent.py`,
`services/agent_plans.py`, and `services/coaching.py` contain older flows.
Do not copy them as the default pattern for new coaching work.

`docs/running-coach-workflow.md` and `docs/handoff.md` include an earlier automatic
activation design; `planning/remaining_mvp/` contains design/task history. They
are useful for rationale, not evidence that those contracts are current. Inspect
the relevant implementation and tests when documents disagree. Explicit current
user instructions set the requested direction; code describes what works today.
Update affected contracts together when intentionally changing direction.

Do not hard-code the athlete's current profile, schedule, symptoms, or migration
head from a dated document. Read structured live state when the task needs it.

## How the coach and athlete interact

- The athlete speaks naturally: a Sunday review, today's adjustment, a new goal,
  a question, or feedback on a draft. Route to the appropriate skill operation;
  do not make the athlete choose protocol names or re-enter known history.
- Sunday evening is the normal review cadence, with extra reviews for material
  changes, symptoms, or goals. This is user initiated, not an automatic schedule.
  Route missing/due blocks to block review; otherwise review the rolling plan.
- Start from compact live snapshots and the accepted block/calendar, recent
  actuals, reported response, confirmed strength/mobility commitments, and selected
  verified KB evidence. Ask only for essential missing facts. Missing is unknown.
- Give concrete, dated, usable prescriptions with purpose, effort, dose, reasons,
  uncertainty, and the feedback that would change the decision. Distinguish
  observations, research, and athlete-specific inference. Keep audit IDs in saved
  structured data rather than cluttering the conversation.
- A requested review authorizes inspection and saving a pending proposal without
  another conversational permission step. An explanatory question alone does not
  require a proposal. Follow the skill for model selection, access, and submission.
- Check for an active draft first. Revise its stable ID/link when refining it;
  refresh stale evidence and honor revision conflicts. The athlete reviews and
  accepts changes in the app. Submission does not activate a plan. Report that
  distinction accurately; do not use an older automatic endpoint to bypass it.
- The next review should read saved decisions, actuals, and feedback, so the athlete
  does not have to retell the week. Preserve completed/locked history and explicit
  restrictions. Do not invent symptoms, completion, physiological thresholds, or
  injury clearance from missing data or wearable summaries.

These are the current product semantics, not a requirement to preserve them
forever. Engineering velocity does not itself change coaching authorization.

## Local development and verification

From repo root: `make doctor`; on a fresh checkout, `make setup`. Local PostgreSQL
is managed by `make db-start` / `make db-stop`. `make dev` starts API, worker, and
Vite; `make build` then `make start` serves the built app. Do not run both servers
at once. Runtime details and full setup are in [README.md](README.md).

- `make check`: backend lint/types/unit tests and frontend lint/types/tests/build.
- `make test-integration`: migrates and tests the isolated PostgreSQL test DB.
- `python3 scripts/test_coach_skill_v2.py`: current helper contract/manifest checks.
- `make test-e2e`: Playwright; requires the appropriate demo server/seed. See
  README's verification instructions before running it.

`.env` may select real mode. Use `./scripts/with-mode test ...` or
`./scripts/with-mode demo ...` explicitly for synthetic writes; never seed/test
against real data. `make migrate`, `make sync`, and server startup can affect the
configured workspace; check the intended mode first. Back up before real schema
changes. Keep `.env`, credentials, raw files, and athlete payloads private; do not
print or commit them. Use the coach helper's filtered access for coaching.

Keep this map and scoped guidance current when moving entry points. At handoff,
report the result, meaningful checks, and any remaining breakage/completion plan.
