# Garmin Personal API capability inventory

Checked 2026-11-10. This app uses Garmin's **official Personal API** for the
owner's own account, through Garmin's official Python client version **1.0.0**.
An authorized schema-only probe of one personal account on 2026-11-10 confirmed
field names and types without printing values or saving a response fixture. No
export or rate-limit headers were available. Values and aggregates still need
private source comparison before real-data acceptance.

## Sources checked

- [Personal API overview](https://developer.garmin.com/gc-developer-program/personal/personal-api)
- [Personal API FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq)
- [Personal API Swagger entry](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/) (interactive schema was not readable in the documentation crawler)
- [Official Python client and wrapper table](https://github.com/garmin/connect-personal-api-python/blob/main/README.md)
- [Package 1.0.0](https://pypi.org/project/garmin-connect-personal-api-python/1.0.0/)
- [Developer Program access tiers](https://developer.garmin.com/gc-developer-program/overview/)

| Dataset | Official Python wrapper / endpoint | Mapping and limits |
| --- | --- | --- |
| Activities | `search_activities(start, limit, start_date, end_date)` / `GET /activitylist-service/activities/search/activities` | Offset paging, 20/page default in official CLI example; this app requests bounded pages. Live summary fields include `activityId`, `ownerId`, `startTimeGMT`, `startTimeLocal`, `activityType.typeKey`, `distance`, `duration`, `elapsedDuration`, `movingDuration`, `averageHR`, `averageRunningCadenceInStepsPerMinute`. SI units require private source comparison. End-date inclusivity remains unverified. Do not assume one page is complete history. |
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

No export adapter is implemented because no actual Garmin export was supplied
to inspect. Unsupported archives are rejected; no archive path or JSON schema
is guessed. The immutable raw-object store can preserve an inspected future
format after it is specified. Multisport parent summaries are excluded from run
volume until child semantics are verified.
