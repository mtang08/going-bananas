# Implementation worker contract — MVP-1.0

Applies only AFTER user approval of the finished plan. Planning agents must not execute these steps. Source: original going_bananas_sol_worker_contract.md and final planning prompt §F–H; adapted to current repository.

## 1. Role and reading

Implement one frozen packet. Read that packet, cited sections in planning/remaining_mvp, then named source/tests and their direct exported dependencies. No research or product design. No broad refactors. If requirements conflict or source differs materially, report a precise blocker to the supervising Astra lead; do not choose silently.

Hierarchy: root manager owns integration; Astra low/medium leads review each Sol low-effort implementer. Luna may perform bounded mechanical tasks only. With four active slots, schedule root + one lead + up to two workers, or root + two leads + one worker. Do not fill all slots with idle supervisors. No model choice overrides without the user's existing authorization.

## 2. Pinned workspace

Integration owner supplies: exact task branch/worktree, immutable dependency-complete commit SHA/tag gb-mvp1-task-<ID>-base[-rN], spec revision, and sanitized synthetic environment. Baseline lineage starts main5ebf981aa4517f4f73f3c97aa5d43232204466ce. A later task uses merged prerequisites, never the bare old SHA. No reused integration/p0 or oldgb-wave tags.

Worktrees: /Users/mtang/dev/going-bananas/private/implementation-worktrees/task-<ID>; no ancestor directory literally named integration (test marker classification depends on path parts). Start with git rev-parse HEAD and git status --porcelain; require supplied base and clean worktree. Setup via make setup. Owner provisions 0600 environment with synthetic demo/test databases on dedicated cluster 55439; no copied main .env, real key or real URL. Worker checks environment file presence/mode without printing contents. Pure-only tasks need no running database.

Shared caches may use /Users/mtang/dev/going-bananas/private/cache/uv and /Users/mtang/dev/going-bananas/private/cache/playwright. Worker never inspects other private files. Owner verifies database identity with redacted checks before granting integration access; test suffix alone is insufficient (host/port/database allowlist required). Never use shared 55432 or garmin_real. Owner alone creates/starts/stops disposable clusters and resets synthetic databases.

## 3. Verification

| Check | Command | Rule |
| --- | --- | --- |
| Routine task gate | make check | Once after edits; rerun after relevant fixes |
| Focused backend test | ./scripts/with-mode test bash -c 'cd backend && uv run pytest <owned-test-path> -q' | Owned tests only; DB tests marked integration |
| Focused frontend test | ./scripts/run bash -c 'cd frontend && npx vitest run <owned-test-path>' | No network/live data |
| Integration | make test-integration | Only assigned packets, owner-granted exclusive DB lease |
| Browser | make test-e2e |050/070; isolated demo server/ports supplied by owner |

Owner serializes migrations and shared test DB access; workers report waiting instead of running concurrent destructive setup. Each command must report actual exit/summary, or not run with reason. Pre-existing red checks are reproduced in a separate clean baseline checkout, never by stashing shared edits. Do not weaken assertions or write implementation-mirroring tests; packet oracles cover meaningful regressions.

## 4. Ownership and data

Only exact paths listed in packet may change. One owner for shared files per wave.003 alone authors0010–0015 migrations; retain all0001–0009 byte-for-byte. No dependency/lockfile changes remain authorized;002 is already complete. Use locked setup only. No directory-wide formatting. No real data fixtures, coordinates outside raw FIT, credentials, snapshots or logs in commits. Never print/copy .env, tokens, connection strings or actual training records. Synthetic fixtures only.

No live-mode commands, sync, deployment, installed external-skill mutation or cutover by ordinary workers.068 implements/test-drives the cutover on synthetic data; integration owner handles real activation under release protocol. Workers never edit planning docs; blockers go to lead for amendments.

## 5. Commits and report

Workers commit only owned reviewed changes on task/<ID>[-rN], message TASK-<ID>: <outcome>. No push, shared reset, tags, main merge or PR. Root may integrate green complete tasks to main under standing user authorization after final planning approval. Existing app must remain functional at each integration point.

Return:
TASK / STATUS completed|blocked / BRANCH / BASE / HEAD / SPEC VERSION
CHANGED FILES (name-status) / OWNERSHIP yes|no
COMMANDS (actual exits and concise summaries)
ACCEPTANCE (each binary criterion with evidence)
BLOCKERS/DEVIATIONS (none or precise path, expected vs actual, decision needed)

## 6. Stop conditions

Wrong baseline, dirty worktree, missing synthetic environment, DB identity failure, unowned-file need, missing dependency, unspecified behavior, conflicting contracts, shared-interface drift, or secret exposure: stop dependent work and report. Do not invent schemas, science, API mappings, UI behavior or recovery procedures. A blocked task cannot be called complete. Lead/manager corrects and re-pins only affected work; unrelated authorized tasks continue.
