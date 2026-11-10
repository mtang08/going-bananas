# Verification and release gates

All cases are planned. Use pytest for domain/backend, a real isolated PostgreSQL
database for persistence tests, frontend component tests for interactions, and
Playwright for cross-layer flows. Do not test PostgreSQL behavior using SQLite.
Freeze time where relevant and use independent expected values rather than
calculating expectations with the implementation being tested.

`make check` must run backend lint/type checks/unit tests, frontend lint/type
checks/component tests, and production build. Separate integration/E2E commands
start or require disposable test databases and fail clearly if unavailable.
No real credentials or private fixtures in tests, screenshots, traces, or CI.

## Required cases

| ID | Case and independently checkable expected result |
| --- | --- |
| V01 | Import identical activity/page/archive twice: one canonical activity, no extra volume, unchanged semantic data revision on second import; attempt audit may increase |
| V02 | Same Garmin ID from API/export, both arrival orders: one activity, selected comparable fields match defined precedence, source revisions retained |
| V03 | Later source revision changes distance; annotations survive; weekly total/context changes once; stale saved snapshot is identified |
| V04 | No-ID identical replay dedupes; merely similar runs aren't auto-merged; conflict queue excludes uncertain additions and discloses withheld counts; keep-separate/merge/reversal survive replay |
| V05 | Failed page doesn't advance its checkpoint; retry/restart commits successful rows once; previous datasets remain readable |
| V06 | Invalid field/type/missing timezone and negative/NaN values produce per-record errors; valid records still import; zero distance gives no pace, missing distance remains unknown |
| V07 | Source `2026-01-01T01:00:00Z` displays Dec 31 in New York; original timestamp preserved; cross-midnight run counted on local start date |
| V08 | New York DST dates March 8 and Nov 1, 2026: local date windows work despite 23/25-hour days; ambiguous unzoned source time cannot silently become UTC |
| V09 | Mixed-account import rejected; parent/child multisport doesn't double-count; missing source record is not treated as deletion |
| V10 | At end of Nov 15, 2026 NY time: runs Nov 2=1609.344m, Nov 8=3218.688m, Nov 9=4828.032m, Nov 15=6437.376m. Rolling 14 dates totals 10mi, rolling 7 and current week total 7mi; Nov 1 is excluded from rolling 14. Include strength with 10km metadata and verify it adds no running miles |
| V11 | 1609.344m and moving 600s → 10:00/mi; missing/zero distance yields null; elapsed 700s remains separate. Longest elapsed chooses 700 over another run with elapsed 650 even if moving time differs |
| V12 | Three HRV observations 40, 50, 60ms in a seven-date window yield observed mean 50ms with n=3/7; gaps stay gaps; all absent produces null, not 0. Unknown workout labels remain an explicit bucket |
| V13 | Anchor Nov 2, 2026: opportunities Nov 2,4,6,8,10,12,14,16; seven in Nov 2–15. Miss Nov 6: Nov 8 remains eligible. Test year and DST boundaries and dates before anchor |
| V14 | No anchor: unscheduled state. Draft may be incomplete; acceptance rejects extra/duplicate/non-parity run days and insufficient confirmed strength; actual off-cycle run still imports |
| V15 | Run ends Nov 2 09:00 local: Nov 3 09:00 feedback is +24h and Nov 4 01:00 is +40h. Another run/strength session stays a separate candidate; no causal assignment. DST test computes actual elapsed hours, not date-difference×24 |
| V16 | No check-in is unknown; one-tap explicitly writes none/normal/usual. Two observations same day preserved. Network retry with same idempotency key creates one; correction keeps old version and recomputes associations |
| V17 | Accepted plan version retained after new proposal/rejection; completion link requires confirmation; duplicate links rejected; unknown coverage gives unlinked/pending, not fabricated missed/completed |
| V18 | Manual strength then Garmin record creates resolution candidate; resolving yields one counted session, preserves manual note; no dose/tonnage/calorie target generated |
| V19 | Concurrent import attempts plus database uniqueness prevent duplicates; null update doesn't erase known data; explicit documented invalidation removes value with source history retained |
| V20 | Dashboard has demo/real labels, date/unit tooltips, tables for charts, keyboard check-in, narrow viewport, and loading/empty/partial/stale/error states. Metric shown equals summary API |
| V21 | 429 delta and HTTP-date Retry-After honored; timeouts/5xx bounded retries; invalid schema fails explicitly; repeated cursor/page stops incomplete rather than infinite loop |
| V22 | Token expiry refreshes using supported client; unexpected 401 triggers at most one forced renewal; revoked/expired key stops, shows attention state, never logs canary secret/body |
| V23 | Simultaneous startup/manual/scheduled sync yields one active worker job; interrupted job resumes; sleep/missed schedule catches up; successful activity sync doesn't mark failed HRV fresh |
| V24 | Backup restored into NEW database and private directory preserves check-ins, plans, sources, raw checksums; original DB untouched; missing blob/corrupt backup fails validation |
| V25 | Foreign Origin/Host mutations rejected, GET can't mutate, static server can't read private files, path traversal/zip bombs/symlinks rejected, free-text HTML rendered inert; canary key absent from logs/API/build/context |
| V26 | Deterministic weekly recap/context share totals and missingness; no training advice or invented recovery values; free-text/coordinates/secrets absent by default; no model/network call on rendering |
| V27 | Missing KB, guide, or workflow cannot activate recommendations; no research-dependent startup failure; future example loader contract preserves prose sections/limitations and separates profile/data |
| V28 | DB restart retains feedback; conflicting edits get 409; clean migration and upgrade from prior committed schema succeed; test reset refuses real DB; demo seed refuses real DB |

Tests for future coaching activation are documented but must not be falsely
reported as executed by this analytics release: poor sleep alone is not automatic
rest; worsening gait/symptoms aren't overruled by favorable scores; missing
recovery is unknown; strength is preserved; KB context/conflicts cited; no
unaccepted schedule changes. Use the research-delivered evaluation cases then.

## Cross-layer smoke flows

1. Empty demo database → seed through import pipeline → inspect overview/detail →
   check in → restart → edit check-in → view symptom association → change units.
2. Configure anchor and confirmed strength dates → draft/accept manual plan →
   link actual → propose revision/reject → verify accepted history unchanged.
3. Mock successful sync plus one failed dataset → inspect freshness → retry →
   revise an activity → confirm totals and saved-snapshot stale marker update.
4. Start production build locally → verify deep-link refresh, no console errors,
   no unintended network services, safe error handling when database unavailable.

## Real-data acceptance (private, no real fixtures committed)

- Configure a key locally or choose the received export. Never paste credentials
  into chat or capture them in command arguments, videos, traces, or test reports.
- Import at least one available week of real activity history, expanding to
  28 days when available. Include a strength activity if one exists; don't invent
  data to meet a sample count. State exact retrieved coverage and limitations.
- Compare at least three activities, or all if fewer exist, against their actual
  source: ID, local date, distance, moving/elapsed duration, sport. Include an
  older/newer activity and a boundary case when available. Document source field
  precision; no unexplained discrepancies. Compare aggregate totals using an
  independent sum of selected source records, not the dashboard API itself.
- Verify actual recovery fields/units if available; if unavailable the release
  must accurately say so rather than blocking the activity path or faking values.
- Re-import identical range: no count/total change. Perform a source correction
  test synthetically if changing real Garmin data would be inappropriate.
- Save/correct a real check-in, restart, inspect preceding activities, create a
  manual plan only with confirmed configuration, and confirm comparison view.
- Run backup restore into an isolated target. Confirm real raw/profile files are
  ignored and no secrets were committed. Report only verification outcomes,
  coverage and unresolved issues in tracked documentation.

## Release evidence

Record commit identifier if available, dependency/tool versions, commands,
exit status, date, passing cases, skipped cases with reasons, and unresolved
limitations. Scope assertions carefully: fixture success ≠ real ingestion success;
an API request success ≠ complete history; analytics MVP ≠ adaptive coach.
No arbitrary test coverage percentage substitutes for the required behaviors.
