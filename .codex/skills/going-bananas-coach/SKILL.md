---
name: going-bananas-coach
description: Review Going Bananas training, adapt today's session, and draft running-plan changes for review using live training evidence. Use for athlete check-ins and training goals; not dashboard development.
---

# Going Bananas coach

Use Codex to coach this athlete from the local app and its verified running research. Source version: `running-coach.v1`. All plan changes remain pending until the athlete reviews them in the app.

Choose the smallest fitting operation from [coaching-workflows.md](references/coaching-workflows.md). Use `scripts/coach_app.py --mode real` for the athlete; use `--mode demo` only when explicitly evaluating synthetic examples. Keep the same mode throughout. [app-access.md](references/app-access.md) explains commands and errors.

1. Get a fresh `snapshot --operation OP`. Read its payload and returned KB excerpts. Use its listed drill-down queries only when needed. Do not read raw files, credentials, GPS, check-in notes, or the full research corpus to fill gaps.
2. Explain the proposed training decision using the actual observations and cite the returned evidence/policy/recipe IDs. Treat missing data as unknown. Preserve confirmed strength schedules, completed and locked sessions, and existing restrictions. Do not infer numeric symptoms from legacy categorical check-ins.
3. Obtain `schema`, then write a JSON proposal matching that schema. Preserve the snapshot ID and calendar/block bases exactly. Use only IDs returned in the snapshot/excerpts. Include changes and reasons, preserved items, uncertainty and follow-up. A no-change review is an empty proposal.
4. Run `submit --file PATH`; the helper stores a private copy and submits it as pending. Never call a proposal decision/acceptance endpoint or the former automatic agent-plan endpoint. Do not generate a new proposal as a retry after a decision was made.
5. Summarize the proposed changes and include the returned app review link. Say **“Pending your review; nothing applied.”** For no-change proposals, explain that the app records the athlete's acknowledgment.

For invalid proposals, use structured field errors for at most two corrected submissions. For stale evidence, take one fresh snapshot and regenerate once. If research is unavailable or the app reports that planning is not active, report that status without falling back to an old workflow. No silent acceptance or endless retries.

Use protected calendar undo only when the athlete explicitly requests undo; inspect history first and explain which completed/locked sessions will remain protected. This skill does not authorize messages, purchases, or external account changes.
