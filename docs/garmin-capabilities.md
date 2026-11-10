# Garmin Personal API capability inventory

Checked 2026-11-10. This app uses Garmin's **official Personal API** for the
owner's own account, through Garmin's official Python client version **1.0.0**.
An authorized schema-only probe of one personal account on 2026-11-10 confirmed
field names and types without saving a response fixture. A supplied Garmin
account export was subsequently inspected locally, imported, and replayed.
No numeric rate-limit headers were available.

## Sources checked

- [Personal API overview](https://developer.garmin.com/gc-developer-program/personal/personal-api)
- [Personal API FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq)
- [Personal API Swagger entry](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/) (interactive schema was not readable in the documentation crawler)
- [Official Python client and wrapper table](https://github.com/garmin/connect-personal-api-python/blob/main/README.md)
- [Package 1.0.0](https://pypi.org/project/garmin-connect-personal-api-python/1.0.0/)
- [Developer Program access tiers](https://developer.garmin.com/gc-developer-program/overview/)

| Dataset | Official Python wrapper / endpoint | Mapping and limits |
| --- | --- | --- |
| Activities | `search_activities(start, limit, start_date, end_date)` / `GET /activitylist-service/activities/search/activities` | Offset paging, 20/page default in official CLI example; this app requests bounded pages. Live summary fields include `activityId`, `ownerId`, `startTimeGMT`, `startTimeLocal`, `activityType.typeKey`, `distance`, `duration`, `elapsedDuration`, `movingDuration`, `averageHR`, `averageRunningCadenceInStepsPerMinute`. End-date inclusivity remains unverified. Do not assume one page is complete history. |
| Activity detail | `get_activity(id)` / `GET /activity-service/activity/{id}` | Available if a summary lacks required fields. This release avoids stream/FIT downloads. Detail response shape requires live confirmation. |
| Sleep | `get_daily_sleep_summaries(start_date,end_date)` | Live rows include `userProfilePK`, `calendarDate`, `sleepTimeSeconds`, separate `napTimeSeconds`. Import main sleep seconds only; source date semantics beyond the named field remain to verify. |
| HRV | `get_daily_hrv_summaries(start_date,end_date)` | Live envelope has `userProfilePk` and `hrvSummaries`; rows include `calendarDate`, `lastNightAvg`, `weeklyAvg`, `lastNight5MinHigh`. Import nightly average as milliseconds, separately from weekly average. |
| Resting heart rate | `get_daily_heart_rate(date)` | Live daily response has `userProfilePK`, `calendarDate`, `restingHeartRate`, separately from min/max and sampled heart rate. Import daily resting bpm. |

The Personal API key is exchanged for an OAuth2 bearer token. The key is not a
bearer token. Garmin says bearer tokens last 24 hours or until key expiry; key
expiry may be 30, 90, 180 days, or one year. Garmin's official client caches the
token, proactively renews it, and supports one forced renewal after an unexpected
401; there are **no refresh tokens**. This app stores a key in a private file and
the official token cache in the private directory. Neither appears in CLI
arguments, logs, API results, backups, or context exports.

The Personal tier is pull-only and includes activity JSON/FIT and health JSON.
Garmin's public tier page does not state a Personal API price or numeric rate
quota. Historical range limit, pagination ordering, date-bound inclusivity,
source modification timestamps, and response time zones have not been verified.
The sampled activity `ownerId` matched sleep/HRV/heart-rate user profile IDs;
the importer binds each page to this stable Garmin account ID. Sync uses
overlapping local-date windows, paging guards,
per-dataset status, and explicit incomplete coverage. Engineering defaults are
14 days for activities and 7 days for recovery, not a claim that older records
cannot change. Business Starter is push-only with no historical data; this app
does not use it.

## Inspected account export

The local `import-export` CLI supports the observed Garmin ZIP structure only.
It validates member paths, sizes, compression ratios, CRCs, account identity,
and activity overlap before applying. The original ZIP and selected JSON member
bytes are preserved privately with SHA-256 provenance. Browser uploads and
arbitrary ZIP/CSV imports are unsupported.

The export contained 179 activity summaries, 429 usable main sleep durations,
416 nightly HRV averages, and 434 daily resting-heart-rate observations. The
activity `userProfileId` matched the API account. All 12 overlapping API
activities agreed across 60 comparable time/measurement fields. Export
distance is centimeters (converted to meters), and elapsed/moving durations
are milliseconds (converted to seconds). Export cadence is omitted because its
semantics differ from the API steps-per-minute field. Track running retains its
running subtype. Sleep duration uses the verified sleep-window-minus-awake
formula; HRV maps only the verified nightly statistic.

The applied import added 167 activities while leaving 12 existing API records
canonical; 163 of the 179 export activities are runs. It added 1,198 recovery
observations among 1,282 parsed observations. Six incomplete sleep rows and 43
rows without resting heart rate were skipped; 1,664 other Health Status metrics
remain only in the preserved source. Observed export ranges are partial
coverage, not proof of complete history. A replay created zero source revisions
and zero canonical changes; 1,572 private raw-object checksums were verified.
Multisport parent summaries remain excluded from run volume until child
semantics are verified.
