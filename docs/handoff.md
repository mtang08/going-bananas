# Implementation agent handoff

Copyable kickoff instruction:

> Implement the analytics MVP defined in README.md and docs/implementation-plan.md,
> docs/contracts.md, and docs/verification.md. Read applicable repository
> instructions first. Work sequentially through M0–M7; keep the app usable at each
> checkpoint. Use the local private athlete brief for profile setup without
> copying personal information into tracked fixtures. Implement and verify the
> current task before expanding scope. Continue autonomously on reversible work;
> ask only for external permissions or genuinely missing input needed now. Do not
> implement research, an LLM runtime, or recommendations. Preserve unknowns and
> the user's meaningful twice-weekly strength. Maintain the ledger below with
> evidence and exact next action. Never claim a gate passed without running it.

## Reading and context budget

Read the implementation plan once, then only relevant contracts/cases per task.
Don't repeatedly load the full athlete history, raw files, or future KB. Keep
decisions and blockers here; private details remain in private storage. Avoid
speculative dependency upgrades, new frameworks, or refactors between gates.
Consult official docs for uncertain SDK behavior; record findings once in the
capability inventory. No sub-agent delegation is requested by this plan.

## Current ledger

| Task | State | Evidence / next action |
| --- | --- | --- |
| Planning | Complete | Four linked handoff documents; no app code exists |
| M0 | Not started | Inspect tool availability, scaffold local services and demo |
| M1 | Not started | Canonical schema, deterministic domain/import tests |
| M2 | Not started | Capability inventory and first available real source |
| M3 | Not started | Deterministic overview and detail UI |
| M4 | Not started | Feedback and manual cycle/plan loop |
| M5 | Not started | Sync reliability, scheduling, backup/restore |
| M6 | Not started | Factual recap and private context export |
| M7 | Not started | Full verification and real-data acceptance |

For each completed task replace “not started” with date, actual files/commands,
test outcomes, and remaining limitations. Keep detailed test output out of this
file; cite the concise release checklist. Do not update tests merely to bless
unexpected metrics; check source semantics and the independent expected result.

## Decisions already made

- Local single-user application; PostgreSQL only; raw files private/immutable.
- Research later, no research artifact or model required for analytics MVP.
- Fixture mode isolated from real mode; no fabricated athlete history.
- Every-other-day runs anchored to a confirmed date; meaningful twice-weekly
  strength; no automatically inferred placement, targets, or progression.
- Knowledge base will be local prose + index, selectively loaded with workflows
  and topic context. No premature rigid policy engine or vector database.
- Manual accepted plan + actual + feedback is persisted now; recommendations
  and their acceptance/versioning arrive with the later coaching phase.

## External gates and when to ask

| Missing input | When actually required | Work that can continue |
| --- | --- | --- |
| Compatible Python/Node/Postgres tooling | Running scaffold/tests | Prepare files and setup docs, report unverified execution |
| Local Garmin key or actual export path | Live import/acceptance | Fixture implementation, all synthetic failure tests |
| Confirmed run anchor, strength rotation, quality/long placement | Accepting a real dated plan | Blank setup UI and synthetic cycle tests; show unscheduled real state |
| Rehab instructions, updated symptoms/fitness | Later individualized coaching | Analytics preserves dated observations/unknowns |
| Local running_coach_kb | Later adaptive coaching activation | All M0–M7 analytics work |

Never request key contents. Ask the user to configure a protected file and give
only its path if needed. Don't ask for nonblocking race dates, lifting loads,
research timing, calorie intake, or training paces to build the dashboard.

If API documentation/access is unavailable, finish fixtures and the rest of the
app and clearly report the unsatisfied live-import gate. Do not substitute an
unofficial scraping library or implement invented Garmin endpoint schemas.

## Known verification status

Planning inspection found an empty repository. Python's system command existed;
Node, Docker, and psql were not on that shell's PATH. This is not a conclusive
machine inventory; recheck before installation. Garmin official documentation
and client README were accessed on 2026-11-10. Capability limits, pricing, live
responses, and client integration remain unverified. No tests or app have run.

Verified documentation starting points:

- [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api/)
- [FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/)
- [Swagger](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/)
- [Official Python client](https://github.com/garmin/connect-personal-api-python)

The client README exposes activity, sleep, HRV, and daily summary wrappers;
that is not proof every desired field exists for this athlete. Verify payloads
and limits before mapping. Credentials and live data stay outside agent context
by default; inspect only necessary schema/aggregate information locally.
