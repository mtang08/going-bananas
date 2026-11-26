-- $1 is the observation instant. All date windows use the current athlete timezone.
WITH settings AS (
    SELECT coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') AS tz
), clock AS (
    SELECT tz, ($1::timestamptz AT TIME ZONE tz)::date AS today FROM settings
), eligible_runs AS (
    SELECT a.*, (a.start_at AT TIME ZONE tz)::date AS day
    FROM activities a CROSS JOIN clock
    WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
      AND a.start_at >= ((today-37)::timestamp AT TIME ZONE tz)
      AND a.start_at < ((today+1)::timestamp AT TIME ZONE tz)
      AND NOT coalesce((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
), checkins AS (
    SELECT c.id,c.kind,c.observed_at,c.recorded_at,(c.observed_at AT TIME ZONE tz)::date AS local_date,
        c.fatigue,c.illness,c.gait_change,c.context_tags,c.activity_id,
        coalesce(c.activity_id, CASE WHEN symptoms.items IS NOT NULL AND NOT starts_with(c.idempotency_key,'phone-first-steps:')
            THEN (SELECT a.id FROM eligible_runs a
                  WHERE a.day BETWEEN (c.observed_at AT TIME ZONE tz)::date-3 AND (c.observed_at AT TIME ZONE tz)::date
                    AND a.end_at BETWEEN c.observed_at-interval '48 hours' AND c.observed_at
                  ORDER BY a.end_at DESC,a.id LIMIT 1) END) AS linked_activity_id,
        coalesce(symptoms.items,'[]'::jsonb) AS symptoms
    FROM checkins_v2 c CROSS JOIN clock
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(to_jsonb(s)-'checkin_id' ORDER BY s.id) AS items FROM symptom_reports s WHERE s.checkin_id=c.id
    ) symptoms ON true
    WHERE c.observed_at BETWEEN ((today-34)::timestamp AT TIME ZONE tz) AND $1::timestamptz
), runs AS (
    SELECT a.id AS activity_id,a.day AS local_date,a.start_at,a.end_at,coalesce(r.rpe,a.workout_rpe) AS rpe,
           coalesce(r.source,CASE WHEN a.workout_rpe IS NOT NULL THEN 'garmin_fit' END) AS rpe_source,
           r.collected_at AS rpe_at,c.session_uid
    FROM eligible_runs a CROSS JOIN clock
    LEFT JOIN LATERAL (
        SELECT rpe,source,collected_at FROM session_rpe
        WHERE activity_id=a.id AND source IN ('manual','garmin_fit')
        ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1
    ) r ON true
    LEFT JOIN session_completions c ON c.activity_id=a.id
    WHERE a.day >= today-20
), latest_plan AS (
    SELECT DISTINCT ON (session_uid) * FROM calendar_session_revisions
    WHERE calendar_version_number <= coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0)
    ORDER BY session_uid,calendar_version_number DESC,revision DESC
), sessions AS (
    SELECT p.session_uid,p.local_date,p.slot,p.kind,p.recipe_id,coalesce(p.intent,'') AS intent,
        'committed' AS certainty,c.status AS completion_status,c.modification_reason,c.activity_id,
        v.created_at AS planned_at,c.updated_at AS completion_updated_at
    FROM latest_plan p JOIN calendar_versions v ON v.number=p.calendar_version_number
    LEFT JOIN session_completions c ON c.session_uid=p.session_uid CROSS JOIN clock
    WHERE NOT p.deleted AND p.local_date BETWEEN today-21 AND today+6
), assessments AS (
    SELECT m.subject_key,m.reason_codes,
        (SELECT component->>'status' FROM jsonb_array_elements(m.value->'components') component
         WHERE component->>'name'='target_coverage' LIMIT 1) AS target_coverage
    FROM sessions s CROSS JOIN clock JOIN metric_results m ON true
    WHERE s.local_date<=today AND m.subject_key=s.session_uid::text AND m.is_current
      AND m.metric_id='planned_actual_session' AND m.method_version='v2'
), adverse_nights AS (
    SELECT (today-n)::text AS day FROM clock CROSS JOIN generate_series(0,3) n
    JOIN metric_results m ON m.is_current AND m.metric_id='recovery_multisignal_summary' AND m.method_version='v1'
    WHERE m.subject_key='night:'||(today-n)::text AND EXISTS (
        SELECT FROM unnest(ARRAY['sleep','hrv','resting_hr']) signal WHERE m.value->signal->'adverse'='true'::jsonb
    )
), events AS (
    SELECT e.id,e.name,e.event_date,e.purpose,e.status,matched.has_run_on_date,matched.run_end_at
    FROM events e CROSS JOIN clock CROSS JOIN LATERAL (
        SELECT count(*)>0 AS has_run_on_date,max(r.end_at) AS run_end_at FROM runs r WHERE r.local_date=e.event_date
    ) matched
    WHERE e.event_date BETWEEN today-7 AND today
)
SELECT today::text,tz,
    coalesce((SELECT jsonb_agg(c ORDER BY observed_at,recorded_at,id) FROM checkins c),'[]'::jsonb),
    coalesce((SELECT jsonb_agg(r ORDER BY start_at,activity_id) FROM runs r),'[]'::jsonb),
    coalesce((SELECT jsonb_agg(to_jsonb(s)-'slot' ORDER BY local_date,slot,session_uid) FROM sessions s),'[]'::jsonb),
    coalesce((SELECT jsonb_object_agg(subject_key,to_jsonb(a)-'subject_key') FROM assessments a),'{}'::jsonb),
    coalesce((SELECT jsonb_agg(day ORDER BY day) FROM adverse_nights),'[]'::jsonb),
    coalesce((SELECT jsonb_agg(e ORDER BY event_date,id) FROM events e),'[]'::jsonb)
FROM clock
