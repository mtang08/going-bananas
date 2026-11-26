WITH metadata AS (
 SELECT coalesce((SELECT calendar_head_version FROM app_state WHERE id=1),0) AS head,
 coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') AS zone
), current_sessions AS (
 SELECT DISTINCT ON (session_uid) r.* FROM calendar_session_revisions r,metadata
 WHERE head>0 AND calendar_version_number<=head ORDER BY session_uid,calendar_version_number DESC,revision DESC
), week_sessions AS (
 SELECT r.session_uid,r.kind,r.local_date,r.slot,r.intent,r.recipe_id,r.custom,r.revision,r.deleted,
 r.planned_distance_m,r.planned_duration_s,r.structure::text AS structure,c.status,c.match_method,c.modification_reason,
 coalesce(c.activity_id,c.strong_workout_id,c.manual_session_id) AS subject_id,
 CASE WHEN c.activity_id IS NOT NULL THEN 'activity' WHEN c.strong_workout_id IS NOT NULL THEN 'strong_workout'
 WHEN c.manual_session_id IS NOT NULL THEN 'manual_session' END AS subject
 FROM current_sessions r LEFT JOIN session_completions c ON c.session_uid=r.session_uid AND NOT r.deleted
 WHERE r.local_date BETWEEN $1::date AND $1::date+6
), bounds AS (SELECT least($2::date,$1::date+6) AS as_of),
eligible AS (
 SELECT a.id,(a.start_at AT TIME ZONE zone)::date AS local_date,a.timer_s,a.distance_m,a.sport,
 a.avg_hr_bpm,a.moving_s,a.workout_rpe
 FROM activities a CROSS JOIN metadata CROSS JOIN bounds
 WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
 AND ((a.start_at AT TIME ZONE zone)::date BETWEEN least(as_of-27,$1::date) AND $1::date+6
 OR a.id IN (SELECT subject_id FROM week_sessions WHERE subject='activity'))
 AND NOT coalesce((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
), subjects AS (
 SELECT 'activity' AS subject,a.id,a.local_date,'run' AS kind,a.timer_s AS duration_s,a.distance_m,false AS linked,
 a.sport,a.avg_hr_bpm,CASE WHEN a.moving_s>0 AND a.distance_m>0 THEN a.moving_s/(a.distance_m/1000) END AS moving_pace_s_per_km,
 coalesce(r.rpe,a.workout_rpe) AS rpe,coalesce(r.source,CASE WHEN a.workout_rpe IS NOT NULL THEN 'garmin_fit' END) AS rpe_source
 FROM eligible a LEFT JOIN LATERAL (SELECT rpe,source FROM session_rpe WHERE activity_id=a.id
 AND source IN ('manual','garmin_fit') ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1) r ON true
 WHERE a.local_date BETWEEN $1::date AND $1::date+6 OR a.id IN (SELECT subject_id FROM week_sessions WHERE subject='activity')
 UNION ALL
 SELECT 'strong_workout',w.id,w.local_date,'strength',w.duration_s,NULL,false,NULL,NULL,NULL,NULL,NULL
 FROM strong_workouts w WHERE resolution_state='resolved' AND (local_date BETWEEN $1::date AND $1::date+6
 OR id IN (SELECT subject_id FROM week_sessions WHERE subject='strong_workout'))
 UNION ALL
 SELECT 'manual_session',m.id,m.date,m.kind,m.duration_s,NULL,linked_activity_id IS NOT NULL,NULL,NULL,NULL,NULL,NULL
 FROM manual_sessions m WHERE date BETWEEN $1::date AND $1::date+6 OR id IN (SELECT subject_id FROM week_sessions WHERE subject='manual_session')
), metrics AS (
 SELECT m.metric_id,m.subject_key,m.status,m.value,
 CASE WHEN jsonb_typeof(m.value->'n_planned')='number' AND m.value->>'n_planned' ~ '^-?[0-9]+$'
 THEN m.value->'n_planned' END AS reps_planned,
 CASE WHEN jsonb_typeof(m.value->'n_completed')='number' AND m.value->>'n_completed' ~ '^-?[0-9]+$'
 THEN m.value->'n_completed' END AS reps_completed,m.reason_codes,m.quality_flags FROM metric_results m
 WHERE m.is_current AND m.method_version='v2' AND
 ((m.metric_id='planned_actual_session' AND m.subject_key IN (SELECT session_uid::text FROM week_sessions WHERE NOT deleted))
 OR (m.metric_id='work_interval_execution' AND m.subject_key IN (SELECT subject_id::text FROM week_sessions WHERE subject='activity')))
)
SELECT head,zone,
 (SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY distance_m/timer_s) FROM eligible,bounds
  WHERE local_date BETWEEN as_of-27 AND as_of AND timer_s>0 AND distance_m>0 AND timer_s<'Infinity' AND distance_m<'Infinity'),
 NOT EXISTS (SELECT 1 FROM generate_series($1::date,least($1::date+6,$2::date),interval '1 day') d
 WHERE NOT EXISTS(SELECT 1 FROM coverage_intervals WHERE dataset='activities' AND status='complete'
 AND fully_enumerated AND d::date BETWEEN start_date AND end_date)),
 coalesce((SELECT json_agg(s ORDER BY local_date,slot,session_uid) FROM week_sessions s),'[]'),
 coalesce((SELECT json_agg(s ORDER BY local_date,kind,id) FROM subjects s),'[]'),
 coalesce((SELECT json_agg(m) FROM metrics m),'[]')
FROM metadata
