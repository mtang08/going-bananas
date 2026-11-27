The JSON files capture the Python HTTP reference at commit `e5e565d` using
the original synthetic seeds in `scripts/rewrite/check_activity_reads.py`
and `scripts/rewrite/check_annotations.py`. The reference clock was
2026-11-26 12:00 UTC. Request IDs were stripped as in the original comparison.
The annotation fixture also captures the final rows selected by its state
queries after all PATCH requests ran in order.
