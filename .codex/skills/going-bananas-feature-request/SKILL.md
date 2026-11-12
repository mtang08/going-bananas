---
name: going-bananas-feature-request
description: Record or refine a Going Bananas feature request in the project backlog using a consistent, concise template. Use when the user asks to save a feature idea for later implementation; not for building it or ordinary brainstorming.
---

# Record a feature request

Save enough product intent for a later implementation agent to understand what to build. This is a small capture task: no research, code inspection, technical design, estimates, or implementation unless separately requested.

## Workflow

1. Use the Going Bananas repository (normally `/Users/mtang/dev/going-bananas`). Read `docs/backlog.md` and the relevant user messages. Treat statements about current behavior as user reports unless already verified.
2. If the same request already exists, refine that entry and retain its ID, original date, and confirmed decisions; add an updated date. Otherwise allocate `IDEA-###` as one greater than the highest ID anywhere in the file, including outside the inbox. Add the entry at the end of **Feature ideas inbox**, before the next level-two heading. Keep unrelated text intact.
3. Fill the template below, usually in 100–250 words. Derive acceptance checks from the requested behavior; do not invent additional requirements, architecture, priorities, or commitments. Keep implementation suggestions from the user as suggestions unless they explicitly require them. Use `Unspecified` or `None identified` instead of guessing.
4. Save immediately. Missing implementation details belong in **Open questions**. Ask one concise batch only if the intended outcome or scope is too ambiguous to capture usefully; save the known intent first. Recording an idea does not authorize building it.
5. Reply with the ID, title, and a link to the saved entry. Mention any important unresolved question; do not repeat the entire entry.

Keep separate independently useful requests in separate entries. Link related IDs rather than merging distinct outcomes. Do not reformat the existing backlog or mark work implemented without evidence.

## Entry template

```markdown
### IDEA-### — Short, concrete title

Recorded YYYY-MM-DD. Status: idea. Priority: Unspecified.

**Problem / context**
When or where the need occurs, the current behavior as reported, and why it matters.

**Desired behavior**
What the user should be able to do and what should happen. Include a short
trigger → action → result example when it makes the request clearer.

**Acceptance checks**
- Observable outcome that would demonstrate the request works.
- Another check only if needed, including a user-specified edge case.

**Constraints**
User-specified requirements, exclusions, or dependencies; otherwise Unspecified.

**Open questions**
Unresolved product choices that could change the implementation; otherwise None identified.
```

Use a user-specified priority or existing status when provided. For refinements, add `Updated YYYY-MM-DD` to the metadata. Omit the second acceptance bullet if one suffices. Add `Related: IDEA-###` only when relevant. Replace all template instructions with actual content.
