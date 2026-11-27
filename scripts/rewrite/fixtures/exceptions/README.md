# Exception reference fixtures

These cases were captured from the Python app at `e5e565d`, using the deterministic seed and clock in the exception rewrite checks and a disposable migrated PostgreSQL schema.

- `http-cases.json` records the request sequence, status codes and complete response bodies. Request IDs are omitted because each request generates a new ID.
- `http-state.json` records the ordered findings, patches and data revision after that sequence.
- `view-*.json` records active and recent projections at three instants across the day and recency cutoffs, before population, after population and after proposal decisions.
