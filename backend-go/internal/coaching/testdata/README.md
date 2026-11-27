# Coaching reference fixtures

The reference cases under this package were captured from the Python implementation at commit `7e759fb` using deterministic synthetic inputs. Tests load the saved cases directly in Go.

- `drafts/testdata` keeps representative proposal shape and ordered rule results, including partial decisions. Rules share saved contexts and retain the authored field order.
- `snapshots/testdata` keeps distinct advanced cases, representative payload cases for every operation, and selected knowledge routes. Prepared snapshots compare the captured hashes, verified research version, and token budget. The live replay check separately verifies that derived records keep their IDs.
- `evidence/testdata` keeps ordered SQL changes between six synthetic states, including changes that invalidate saved fingerprints and a restored strength session that retires its prior omission. The tests shadow the migrated tables with temporary copies and compare each canonical source hash, the safety guard, and the planned schedule against the capture.
- `knowledge.json` records verified selections against the repository research package at the same revision. A research-package update can change selection digests and excerpt sizes.
