# Research library guidance

This is evidence for the coach, not live athlete state or an executable training
policy. Inherit the root iteration-speed policy; load only relevant material.

- Start with `README.md` and `COACHING_GUIDE.md`, then one `workflows/` document
  and relevant `topics/`, `policies/`, and `recipes/` records. For routine live
  coaching, use the skill's returned verified excerpts instead of scanning here.
- `references/source_registry.json` and evidence matrices record support;
  `manifest.json` provides integrity metadata. Runtime selection and verification
  live in `backend-go/internal/coaching/knowledge.go` and `backend-go/internal/coaching/evidence/`.
- Candidate policies are not automatically active rules. Distinguish direct
  evidence from generalization and athlete-specific inference. Do not turn a
  research dose or safety bound into a universal prescription.
- For new research, use `.codex/skills/going-bananas-coach/references/research-intake.md` and
  record disposition in `research/coaching_web_intake.md`. Reuse verified sources;
  keep unverified candidates separate from runtime evidence. Update provenance
  and manifest hashes when promoting or changing registered content.
- Keep current athlete details and source originals private. Structured current
  app state supersedes dated context. Never add private payloads to examples.
- `evaluation/` contains behavior cases, not proof they have been executed.
  Validate the affected retrieval/integrity path and relevant cases after changes;
  do not claim coaching quality from schema or transport checks alone.
