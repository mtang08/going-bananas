# TASK-066 — Explicit proposal review and training-block UI

Baseline: main `5ebf981aa4517f4f73f3c97aa5d43232204466ce` plus050/063.
Spec: planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag.
Wave / priority: P0-B; wave 11 (dependency_graph.md).
Dependencies: TASK-064; all earlier DAG dependencies remain required.
File ownership: create `frontend/src/pages/ProposalReview.tsx`, `frontend/src/pages/Block.tsx`, `frontend/tests/proposals.test.tsx`, `frontend/tests/block.test.tsx`; edit `frontend/src/pages/Home.tsx` (pending card only), `frontend/src/api/types/coach.ts` (proposal DTOs/client functions), `frontend/src/styles.css` (new selectors only).
Forbidden changes: App.tsx routing (070), installed skill, backend, existing Coach/Cycle, shared api.ts. No new library.

## Objective and observable end state
Pending proposals show before/after changes with a checkbox per change. User selects which changes to accept; nothing applies on page load. Block/anchor changes have explicit separate controls. One successful decision invalidates shared v2 queries and displays its stored result.

## Inputs and fixed contracts
schemas §§4/6, coaching_contract §§4–5,063 list/detail/decision DTOs. API envelope contains planning_authority. Structure formatting uses039 flattenStructure. Exact headings/buttons: Home “Pending proposal”, “Review proposal”; review “Review proposal”, `Accept change <change_id>`, “Accept selected”, “Reject all”; empty document “Accept (no changes)”; stale “This proposal is stale”; block “Training block” / “No active training block”.

## Implementation procedure
1. Export `ProposalReview({proposalId}:{proposalId:string})`. GET proposal detail under query key ['v2','proposals',proposalId]. Render summary/rationale/confidence, immutable before/after, reasons/material flags, source IDs, missing inputs and follow-up. Dates and quantities preserve explicit missing states. Checkboxes initially unchecked: each changeset item requires review. Block checkbox `Accept block change`; anchors `Accept anchor <key>`.
2. Accept selected sends complete disjoint accept/reject lists plus block/anchor selections, expected_head and UUID idempotency_key. Freeze body/key on first submission; identical network retry reuses them. A selection change before success creates a new key/body. Disable controls during request. No automatic resubmit on409/422. Stale disables acceptance, preserves diff and asks for a new review. Invalid subset shows field errors and keeps selections. Terminal response disables editing; identical replay renders original result.
3. Reject all sends no accepted items, marks every change rejected and false/empty block/anchor selections. Empty proposal offers only “Accept (no changes)” and “Reject all”, recording acknowledgment/rejection without version creation. Success: version present -> `Accepted — calendar version <n>`; absent -> `Decision recorded — calendar unchanged`. Render rejected and partially accepted status accurately.
4. Invalidate calendar, proposals, block, anchors, metrics, prompts and daily guidance after successful decision. Any server authority mismatch disables mutations and displays “Planning upgrade required”; no fallback to old automatic submission.
5. Home queries pending proposals and links to #proposal/ID; multiple pending rows list newest first. Use actual server status; no optimistic activation. Add read-only block card from /blocks/active: objective, review date, maintained qualities, eligible recipe titles and week calculation floor((today-start)/7)+1 / ceil((review-start)/7). Full Block page renders decision history and absent state; no automatic block mutation.
6. Retain legacy review-history link #coach and eligibility-driven undo display. Imported legacy_unstructured changes render original prose without invented planned reps.

## Tests and expected results
`cd frontend && npx vitest run tests/proposals.test.tsx tests/block.test.tsx` then frontend build. Test three changes accept c1/c3 reject c2 exact payload; no request on mount; selection controls initially unchecked; invalid subset retains selection; stale disabled; reject-all/no-change writes no version; retry identical key/body; selection change changes key; completed state cannot decide differently; null/legacy structure rendering; missing/active block and history; legacy authority disabled.

## Acceptance checklist
- [ ] Every activation requires explicit decision; no default selected changes.
- [ ] Current Coach/Cycle remain unchanged and inspectable.
- [ ] Retry and conflict UI reflect server truth; source evidence visible.

## Completion report
Changed paths, test/build output, DTO examples; blockers.

## Escalation rule
Report missing response fields to lead. Do not infer version numbers, activation status or acceptance dependencies.
