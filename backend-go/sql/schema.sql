SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_table_access_method = heap;

CREATE TABLE public.activities (
    id uuid NOT NULL,
    source_account_id uuid,
    garmin_id character varying(100),
    source_identity character varying(256),
    start_at timestamp with time zone NOT NULL,
    original_start character varying(100) NOT NULL,
    source_timezone character varying(100),
    local_date date NOT NULL,
    sport character varying(50) NOT NULL,
    subtype character varying(80),
    distance_m double precision,
    elapsed_s double precision,
    moving_s double precision,
    avg_hr_bpm double precision,
    cadence_spm double precision,
    source_workout_label character varying(40),
    canonical_revision integer NOT NULL,
    resolution_state character varying(30) NOT NULL,
    field_provenance jsonb NOT NULL,
    timer_s double precision,
    end_at timestamp with time zone,
    fit_file_id uuid,
    workout_rpe numeric(3,1),
    workout_feel smallint,
    fit_status character varying(20) DEFAULT 'not_fetched'::character varying NOT NULL,
    treadmill_interval_paces jsonb,
    CONSTRAINT ck_activities_fit_status CHECK (((fit_status)::text = ANY ((ARRAY['not_fetched'::character varying, 'fetched'::character varying, 'decoded'::character varying, 'unavailable'::character varying, 'decode_error'::character varying])::text[]))),
    CONSTRAINT ck_activities_workout_rpe CHECK (((workout_rpe IS NULL) OR ((workout_rpe >= (0)::numeric) AND (workout_rpe <= (10)::numeric))))
);

CREATE TABLE public.activity_annotations (
    id uuid NOT NULL,
    activity_id uuid NOT NULL,
    version integer NOT NULL,
    workout_label character varying(40),
    notes text,
    excluded boolean NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.activity_laps (
    id uuid NOT NULL,
    activity_id uuid NOT NULL,
    lap_index integer NOT NULL,
    start_at timestamp with time zone NOT NULL,
    timer_s double precision,
    elapsed_s double precision,
    distance_m double precision,
    avg_speed_mps double precision,
    avg_hr_bpm double precision,
    max_hr_bpm double precision,
    lap_trigger character varying(30),
    wkt_step_index integer,
    intensity character varying(20),
    end_at timestamp with time zone,
    CONSTRAINT ck_activity_laps_intensity CHECK (((intensity IS NULL) OR ((intensity)::text = ANY ((ARRAY['active'::character varying, 'rest'::character varying, 'warmup'::character varying, 'cooldown'::character varying, 'recovery'::character varying, 'interval'::character varying, 'other'::character varying])::text[]))))
);

CREATE TABLE public.activity_sources (
    id uuid NOT NULL,
    activity_id uuid NOT NULL,
    source_record_id uuid NOT NULL,
    selected_fields jsonb NOT NULL
);

CREATE TABLE public.activity_streams (
    activity_id uuid NOT NULL,
    t_s integer[] NOT NULL,
    hr_bpm smallint[] NOT NULL,
    speed_mps real[] NOT NULL,
    distance_m real[] NOT NULL,
    altitude_m real[] NOT NULL,
    cadence real[] NOT NULL,
    timer_on integer[] NOT NULL,
    sample_count integer NOT NULL,
    max_gap_s integer NOT NULL,
    quality_flags text[] DEFAULT '{}'::text[] NOT NULL
);

CREATE TABLE public.activity_workout_steps (
    id uuid NOT NULL,
    activity_id uuid NOT NULL,
    message_index integer NOT NULL,
    step_name character varying(100),
    intensity character varying(20),
    duration_type character varying(30) NOT NULL,
    duration_value double precision,
    target_type character varying(30),
    target_low double precision,
    target_high double precision,
    repeat_from integer,
    repeat_count integer,
    CONSTRAINT ck_activity_workout_steps_intensity CHECK (((intensity)::text = ANY ((ARRAY['active'::character varying, 'rest'::character varying, 'warmup'::character varying, 'cooldown'::character varying, 'recovery'::character varying, 'interval'::character varying, 'other'::character varying])::text[])))
);

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

CREATE TABLE public.app_state (
    id integer NOT NULL,
    data_revision integer NOT NULL,
    calendar_head_version integer DEFAULT 0 NOT NULL
);

CREATE SEQUENCE public.app_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.app_state_id_seq OWNED BY public.app_state.id;

CREATE TABLE public.block_benchmarks (
    id uuid NOT NULL,
    block_uid uuid NOT NULL,
    block_version integer NOT NULL,
    match_method character varying(8) NOT NULL,
    activity_id uuid,
    event_id uuid,
    protocol character varying(300) NOT NULL,
    distance_m integer,
    local_date date,
    result_s integer,
    outcome character varying(20),
    compared_with character varying(300),
    proposal_id uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_block_benchmarks_match_method CHECK (((match_method)::text = ANY ((ARRAY['auto'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_block_benchmarks_outcome CHECK (((outcome)::text = ANY ((ARRAY['progress'::character varying, 'consolidate'::character varying, 'recalibrate_only'::character varying, 'inconclusive'::character varying])::text[])))
);

CREATE TABLE public.block_decisions (
    id uuid NOT NULL,
    block_uid uuid,
    decision character varying(12) NOT NULL,
    from_version integer,
    to_version integer,
    rationale text NOT NULL,
    evidence_ids text[] DEFAULT '{}'::text[] NOT NULL,
    policy_ids text[] DEFAULT '{}'::text[] NOT NULL,
    confidence character varying(10) NOT NULL,
    proposal_id uuid,
    decided_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_block_decisions_decision CHECK (((decision)::text = ANY ((ARRAY['start'::character varying, 'continue'::character varying, 'extend'::character varying, 'consolidate'::character varying, 'transition'::character varying, 'replace'::character varying, 'end'::character varying])::text[])))
);

CREATE TABLE public.block_versions (
    id uuid NOT NULL,
    block_uid uuid NOT NULL,
    version integer NOT NULL,
    status character varying(16) NOT NULL,
    objective text NOT NULL,
    maintained_qualities text[] DEFAULT '{}'::text[] NOT NULL,
    non_goals text[] DEFAULT '{}'::text[] NOT NULL,
    eligible_recipe_ids character varying(10)[] DEFAULT '{}'::character varying[] NOT NULL,
    progression_dimension character varying(40) NOT NULL,
    constraints jsonb NOT NULL,
    start_date date NOT NULL,
    review_date date NOT NULL,
    early_review_triggers text[] DEFAULT '{}'::text[] NOT NULL,
    objective_status character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    proposal_id uuid,
    benchmark jsonb,
    target_event_id uuid,
    build_outline jsonb DEFAULT '[]'::jsonb NOT NULL,
    why jsonb DEFAULT '[]'::jsonb NOT NULL,
    indicators jsonb DEFAULT '[]'::jsonb NOT NULL,
    legacy_text text,
    CONSTRAINT ck_block_versions_objective_status CHECK (((objective_status)::text = ANY ((ARRAY['unresolved'::character varying, 'partially_achieved'::character varying, 'achieved'::character varying, 'not_achieved'::character varying])::text[]))),
    CONSTRAINT ck_block_versions_progression_dimension CHECK (((progression_dimension)::text = ANY ((ARRAY['duration'::character varying, 'frequency'::character varying, 'long_run'::character varying, 'quality_volume'::character varying, 'intensity'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT ck_block_versions_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'consolidating'::character varying, 'completed'::character varying, 'replaced'::character varying, 'ended'::character varying])::text[])))
);

CREATE TABLE public.blocks (
    id uuid NOT NULL,
    block_uid uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.calendar_session_revisions (
    id uuid NOT NULL,
    session_uid uuid NOT NULL,
    revision integer NOT NULL,
    calendar_version_number integer NOT NULL,
    deleted boolean DEFAULT false NOT NULL,
    local_date date NOT NULL,
    slot smallint DEFAULT '0'::smallint NOT NULL,
    kind character varying(12) NOT NULL,
    recipe_id character varying(10),
    custom boolean DEFAULT false NOT NULL,
    locked boolean DEFAULT false NOT NULL,
    legacy_unstructured boolean DEFAULT false NOT NULL,
    legacy_payload jsonb,
    placeholder boolean DEFAULT false NOT NULL,
    intent character varying(200) NOT NULL,
    certainty character varying(12) NOT NULL,
    planned_duration_s integer,
    planned_distance_m integer,
    structure jsonb,
    strength_slot_id uuid,
    notes text,
    brief jsonb,
    CONSTRAINT ck_calendar_session_revisions_certainty CHECK (((certainty)::text = ANY ((ARRAY['committed'::character varying, 'provisional'::character varying])::text[]))),
    CONSTRAINT ck_calendar_session_revisions_kind CHECK (((kind)::text = ANY ((ARRAY['run'::character varying, 'strength'::character varying, 'cross'::character varying, 'rest'::character varying, 'mobility'::character varying, 'rehab'::character varying])::text[]))),
    CONSTRAINT ck_calendar_session_revisions_planned_distance_m CHECK (((planned_distance_m IS NULL) OR (planned_distance_m > 0))),
    CONSTRAINT ck_calendar_session_revisions_planned_duration_s CHECK (((planned_duration_s IS NULL) OR (planned_duration_s > 0))),
    CONSTRAINT ck_calendar_session_revisions_slot CHECK ((slot >= 0))
);

CREATE TABLE public.calendar_versions (
    id uuid NOT NULL,
    number integer NOT NULL,
    parent_number integer,
    kind character varying(20) NOT NULL,
    actor character varying(10) NOT NULL,
    reason text,
    proposal_id uuid,
    restored_from_number integer,
    block_version_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_calendar_versions_actor CHECK (((actor)::text = ANY ((ARRAY['system'::character varying, 'user'::character varying, 'coach'::character varying])::text[]))),
    CONSTRAINT ck_calendar_versions_kind CHECK (((kind)::text = ANY ((ARRAY['bootstrap'::character varying, 'manual_edit'::character varying, 'proposal_accept'::character varying, 'rollback'::character varying, 'legacy_import'::character varying])::text[])))
);

CREATE TABLE public.checkin_revisions (
    id uuid NOT NULL,
    checkin_id uuid NOT NULL,
    version integer NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE public.checkin_v2_revisions (
    id uuid NOT NULL,
    checkin_id uuid NOT NULL,
    version integer NOT NULL,
    payload jsonb NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.checkins (
    id uuid NOT NULL,
    idempotency_key character varying(100) NOT NULL,
    version integer NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    symptoms character varying(20) NOT NULL,
    change character varying(20),
    gait character varying(20) NOT NULL,
    feeling character varying(20) NOT NULL,
    effort integer,
    activity_id uuid,
    note text
);

CREATE TABLE public.checkins_v2 (
    id uuid NOT NULL,
    idempotency_key character varying(100) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    kind character varying(20) NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    fatigue numeric(3,1),
    illness character varying(10),
    gait_change character varying(10),
    context_tags character varying(30)[] DEFAULT '{}'::character varying[] NOT NULL,
    activity_id uuid,
    prompt_id uuid,
    note text,
    schema_version smallint DEFAULT '2'::smallint NOT NULL,
    pain_reported boolean,
    CONSTRAINT ck_checkins_v2_context_tags CHECK ((context_tags <@ ARRAY['heat'::character varying, 'travel'::character varying, 'poor_sleep'::character varying, 'unusual_surface'::character varying, 'equipment'::character varying])),
    CONSTRAINT ck_checkins_v2_fatigue CHECK (((fatigue IS NULL) OR ((fatigue >= (0)::numeric) AND (fatigue <= (10)::numeric)))),
    CONSTRAINT ck_checkins_v2_gait_change CHECK (((gait_change)::text = ANY ((ARRAY['yes'::character varying, 'no'::character varying, 'unsure'::character varying])::text[]))),
    CONSTRAINT ck_checkins_v2_illness CHECK (((illness)::text = ANY ((ARRAY['none'::character varying, 'possible'::character varying, 'present'::character varying])::text[]))),
    CONSTRAINT ck_checkins_v2_kind CHECK (((kind)::text = ANY ((ARRAY['exception'::character varying, 'post_run'::character varying, 'delayed_followup'::character varying])::text[])))
);

CREATE TABLE public.coach_chat_file_imports (
    mode text NOT NULL
);

CREATE TABLE public.coach_chat_receipts (
    mode text NOT NULL,
    client_message_id uuid NOT NULL,
    digest text NOT NULL
);

CREATE TABLE public.coach_chat_reviews (
    mode text NOT NULL,
    id uuid NOT NULL,
    state jsonb NOT NULL,
    current boolean NOT NULL
);

CREATE TABLE public.coach_decision_keys (
    idempotency_key character varying(100) NOT NULL,
    proposal_id uuid NOT NULL,
    decision_hash character varying(64) NOT NULL,
    result jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.coach_outcome_events (
    id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    status character varying(24) NOT NULL,
    effect character varying(24),
    note text,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.coach_outcomes (
    id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    status character varying(24) NOT NULL,
    effect character varying(24),
    note text,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.coach_plan_revisions (
    id uuid NOT NULL,
    parent_revision_id uuid,
    plan_id uuid,
    workflow character varying(12) NOT NULL,
    as_of date NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    idempotency_key character varying(100) NOT NULL,
    evidence_hash character varying(64) NOT NULL,
    summary text NOT NULL,
    rationale text NOT NULL,
    payload jsonb NOT NULL,
    inputs jsonb NOT NULL
);

CREATE TABLE public.coach_proposal_changes (
    id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    change_id character varying(12) NOT NULL,
    op character varying(10) NOT NULL,
    session_uid uuid,
    before jsonb,
    after jsonb,
    reason text NOT NULL,
    decision character varying(10) NOT NULL,
    CONSTRAINT ck_coach_proposal_changes_decision CHECK (((decision)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT ck_coach_proposal_changes_op CHECK (((op)::text = ANY ((ARRAY['add'::character varying, 'modify'::character varying, 'move'::character varying, 'delete'::character varying])::text[])))
);

CREATE TABLE public.coach_proposal_revisions (
    proposal_id uuid NOT NULL,
    revision integer NOT NULL,
    saved_at timestamp with time zone NOT NULL,
    reason text NOT NULL,
    payload jsonb NOT NULL,
    changed_change_ids text[] NOT NULL,
    changed_fields text[] NOT NULL,
    request_hash character varying(64)
);

CREATE TABLE public.coach_proposals (
    id uuid NOT NULL,
    operation character varying(32) NOT NULL,
    snapshot_id uuid NOT NULL,
    base_calendar_version integer NOT NULL,
    base_block_version_id uuid,
    status character varying(20) NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    decided_at timestamp with time zone,
    headline text NOT NULL,
    confidence jsonb NOT NULL,
    evidence_ids text[] DEFAULT '{}'::text[] NOT NULL,
    policy_ids text[] DEFAULT '{}'::text[] NOT NULL,
    recipe_ids text[] DEFAULT '{}'::text[] NOT NULL,
    escalation character varying(32),
    block_change jsonb,
    anchor_changes jsonb,
    payload jsonb NOT NULL,
    decision_idempotency_key character varying(100),
    decision_hash character varying(64),
    decision_result jsonb,
    validation_errors jsonb,
    skill_version character varying(20) NOT NULL,
    input_hash character varying(64) NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    discarded_at timestamp with time zone,
    why jsonb DEFAULT '[]'::jsonb NOT NULL,
    uncertainty jsonb DEFAULT '[]'::jsonb NOT NULL,
    change_triggers jsonb DEFAULT '[]'::jsonb NOT NULL,
    next_check jsonb,
    coach_note text,
    legacy_text text,
    CONSTRAINT ck_coach_proposals_escalation CHECK (((escalation)::text = ANY ((ARRAY['proceed_or_modify_today'::character varying, 'review_rolling_plan'::character varying, 'review_training_block'::character varying, 'select_quality_session'::character varying, 'recalibrate_intensity'::character varying, 'handle_goal_or_race_change'::character varying, 'exception_review'::character varying, 'post_event_review'::character varying])::text[]))),
    CONSTRAINT ck_coach_proposals_operation CHECK (((operation)::text = ANY ((ARRAY['proceed_or_modify_today'::character varying, 'review_rolling_plan'::character varying, 'review_training_block'::character varying, 'select_quality_session'::character varying, 'recalibrate_intensity'::character varying, 'handle_goal_or_race_change'::character varying, 'exception_review'::character varying, 'post_event_review'::character varying])::text[]))),
    CONSTRAINT ck_coach_proposals_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'accepted'::character varying, 'partially_accepted'::character varying, 'rejected'::character varying, 'stale'::character varying, 'invalid'::character varying, 'discarded'::character varying])::text[])))
);

CREATE TABLE public.coach_recommendations (
    id uuid NOT NULL,
    kind character varying(12) NOT NULL,
    as_of date NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    engine character varying(40) NOT NULL,
    knowledge_version character varying(80) NOT NULL,
    data_revision integer NOT NULL,
    profile_version integer NOT NULL,
    plan_version integer NOT NULL,
    input_hash character varying(64) NOT NULL,
    inputs jsonb NOT NULL,
    payload jsonb NOT NULL,
    selected_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.coach_snapshots (
    id uuid NOT NULL,
    operation character varying(32) NOT NULL,
    as_of date NOT NULL,
    generated_at timestamp with time zone NOT NULL,
    calendar_version_number integer NOT NULL,
    block_version_id uuid,
    data_revision integer NOT NULL,
    payload jsonb NOT NULL,
    source_fingerprint character varying(64) NOT NULL,
    source_versions jsonb NOT NULL,
    kb_digest character varying(64) NOT NULL,
    payload_sha256 character varying(64) NOT NULL,
    kb_package_version character varying(30) NOT NULL,
    kb_routes jsonb NOT NULL,
    approx_tokens integer NOT NULL,
    CONSTRAINT ck_coach_snapshots_operation CHECK (((operation)::text = ANY ((ARRAY['proceed_or_modify_today'::character varying, 'review_rolling_plan'::character varying, 'review_training_block'::character varying, 'select_quality_session'::character varying, 'recalibrate_intensity'::character varying, 'handle_goal_or_race_change'::character varying, 'exception_review'::character varying, 'post_event_review'::character varying])::text[])))
);

CREATE TABLE public.completion_links (
    id uuid NOT NULL,
    planned_session_id uuid NOT NULL,
    activity_id uuid,
    manual_session_id uuid,
    confirmed_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.conflicts (
    id uuid NOT NULL,
    kind character varying(40) NOT NULL,
    status character varying(30) NOT NULL,
    activity_ids jsonb NOT NULL,
    manual_session_id uuid,
    details jsonb NOT NULL,
    resolution character varying(30),
    resolved_at timestamp with time zone
);

CREATE TABLE public.coverage_intervals (
    id uuid NOT NULL,
    dataset character varying(50) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    observed_start date,
    observed_end date,
    status character varying(40) NOT NULL,
    completed_at timestamp with time zone,
    reason character varying(100),
    fully_enumerated boolean NOT NULL
);

CREATE TABLE public.events (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    event_date date NOT NULL,
    distance_m integer,
    status character varying(12) NOT NULL,
    result_s integer,
    version integer DEFAULT 1 NOT NULL,
    purpose character varying(12) NOT NULL,
    goal_time_s integer,
    rank smallint,
    CONSTRAINT ck_events_goal_time CHECK (((goal_time_s IS NULL) OR (goal_time_s > 0))),
    CONSTRAINT ck_events_purpose CHECK (((purpose)::text = ANY ((ARRAY['pr'::character varying, 'benchmark'::character varying, 'training'::character varying])::text[]))),
    CONSTRAINT ck_events_rank CHECK (((rank IS NULL) OR (rank >= 1))),
    CONSTRAINT ck_events_status CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'registered'::character varying, 'completed'::character varying, 'cancelled'::character varying])::text[])))
);

CREATE TABLE public.exception_findings (
    id uuid NOT NULL,
    rule_code character varying(40) NOT NULL,
    rule_version character varying(20) NOT NULL,
    category character varying(24) NOT NULL,
    severity character varying(10) NOT NULL,
    entity_key character varying(160) NOT NULL,
    status character varying(12) DEFAULT 'open'::character varying NOT NULL,
    summary character varying(240) NOT NULL,
    evidence jsonb NOT NULL,
    evidence_at timestamp with time zone NOT NULL,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    patch_id uuid,
    reviewed_by_proposal_id uuid,
    closed_at timestamp with time zone,
    close_note character varying(500),
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_exception_findings_category CHECK (((category)::text = ANY ((ARRAY['symptoms_illness'::character varying, 'training_response'::character varying, 'accumulated_fatigue'::character varying, 'calendar_disruption'::character varying, 'post_event'::character varying])::text[]))),
    CONSTRAINT ck_exception_findings_severity CHECK (((severity)::text = ANY ((ARRAY['observe'::character varying, 'caution'::character varying, 'hold'::character varying, 'escalate'::character varying])::text[]))),
    CONSTRAINT ck_exception_findings_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'addressed'::character varying, 'reviewed'::character varying, 'resolved'::character varying, 'dismissed'::character varying, 'expired'::character varying])::text[])))
);

CREATE TABLE public.exception_patches (
    id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    calendar_version_number integer NOT NULL,
    category character varying(24) NOT NULL,
    severity character varying(10) NOT NULL,
    ladder_level character varying(20) NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    reassess_on date NOT NULL,
    monitor jsonb DEFAULT '[]'::jsonb NOT NULL,
    return_criteria jsonb DEFAULT '[]'::jsonb NOT NULL,
    escalate_criteria jsonb DEFAULT '[]'::jsonb NOT NULL,
    unchanged jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(12) DEFAULT 'open'::character varying NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by character varying(8),
    resolution_note character varying(500),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_exception_patches_category CHECK (((category)::text = ANY ((ARRAY['symptoms_illness'::character varying, 'training_response'::character varying, 'accumulated_fatigue'::character varying, 'calendar_disruption'::character varying, 'post_event'::character varying])::text[]))),
    CONSTRAINT ck_exception_patches_ladder_level CHECK (((ladder_level)::text = ANY ((ARRAY['current_session'::character varying, 'next_session'::character varying, 'next_days'::character varying, 'committed_window'::character varying, 'block'::character varying])::text[]))),
    CONSTRAINT ck_exception_patches_resolved_by CHECK (((resolved_by)::text = ANY ((ARRAY['coach'::character varying, 'athlete'::character varying])::text[]))),
    CONSTRAINT ck_exception_patches_severity CHECK (((severity)::text = ANY ((ARRAY['observe'::character varying, 'caution'::character varying, 'hold'::character varying, 'escalate'::character varying])::text[]))),
    CONSTRAINT ck_exception_patches_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'resolved'::character varying, 'escalated'::character varying, 'superseded'::character varying])::text[])))
);

CREATE TABLE public.fit_files (
    id uuid NOT NULL,
    raw_object_id uuid NOT NULL,
    activity_id uuid NOT NULL,
    zip_sha256 character varying(64) NOT NULL,
    last_attempt_at timestamp with time zone,
    last_error character varying(100),
    fit_sha256 character varying(64),
    profile_version character varying(20),
    sdk_version character varying(20),
    decoded_at timestamp with time zone,
    decode_error character varying(100),
    message_inventory jsonb NOT NULL,
    device jsonb NOT NULL,
    decoder_version integer
);

CREATE TABLE public.gcal_events (
    id uuid NOT NULL,
    google_event_id text NOT NULL,
    event_type character varying(32) NOT NULL,
    google_status character varying(12) NOT NULL,
    summary text,
    location_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    all_day boolean NOT NULL,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    start_date date,
    end_date date,
    start_tz character varying(64),
    end_tz character varying(64),
    transparency character varying(12) NOT NULL,
    response_status character varying(12),
    busy boolean NOT NULL,
    flight_code character varying(8),
    destination_label character varying(120),
    category character varying(16) NOT NULL,
    auto_category character varying(16) NOT NULL,
    category_source character varying(8) NOT NULL,
    flight_confidence character varying(8),
    content_hash character varying(64) NOT NULL,
    google_updated_at timestamp with time zone,
    first_seen_at timestamp with time zone NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    removed_at timestamp with time zone,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_gcal_events_auto_category CHECK (((auto_category)::text = ANY ((ARRAY['flight'::character varying, 'lodging'::character varying, 'ground_travel'::character varying, 'reservation'::character varying, 'out_of_office'::character varying, 'appointment'::character varying, 'work'::character varying, 'social'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_category CHECK (((category)::text = ANY ((ARRAY['flight'::character varying, 'lodging'::character varying, 'ground_travel'::character varying, 'reservation'::character varying, 'out_of_office'::character varying, 'appointment'::character varying, 'work'::character varying, 'social'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_category_source CHECK (((category_source)::text = ANY ((ARRAY['auto'::character varying, 'athlete'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_flight_confidence CHECK (((flight_confidence)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_response CHECK (((response_status)::text = ANY ((ARRAY['needsAction'::character varying, 'declined'::character varying, 'tentative'::character varying, 'accepted'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_status CHECK (((google_status)::text = ANY ((ARRAY['confirmed'::character varying, 'tentative'::character varying])::text[]))),
    CONSTRAINT ck_gcal_events_time_shape CHECK (((all_day AND (start_date IS NOT NULL) AND (end_date IS NOT NULL) AND (start_at IS NULL) AND (end_at IS NULL)) OR ((NOT all_day) AND (start_at IS NOT NULL) AND (end_at IS NOT NULL) AND (start_date IS NULL) AND (end_date IS NULL)))),
    CONSTRAINT ck_gcal_events_transparency CHECK (((transparency)::text = ANY ((ARRAY['opaque'::character varying, 'transparent'::character varying])::text[])))
);

CREATE TABLE public.goals (
    id uuid NOT NULL,
    text text NOT NULL,
    horizon character varying(12) NOT NULL,
    priority smallint NOT NULL,
    status character varying(10) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_goals_horizon CHECK (((horizon)::text = ANY ((ARRAY['3_6_months'::character varying, 'season'::character varying, 'long_term'::character varying])::text[]))),
    CONSTRAINT ck_goals_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'paused'::character varying, 'done'::character varying, 'dropped'::character varying])::text[])))
);

CREATE TABLE public.import_batches (
    id uuid NOT NULL,
    source_kind character varying(50) NOT NULL,
    status character varying(30) NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    adapter_version character varying(80) NOT NULL,
    counters jsonb NOT NULL,
    error_code character varying(100)
);

CREATE TABLE public.intensity_anchors (
    id uuid NOT NULL,
    anchor_key character varying(40) NOT NULL,
    kind character varying(30) NOT NULL,
    value_low double precision NOT NULL,
    value_high double precision,
    unit character varying(8) NOT NULL,
    protocol character varying(24) NOT NULL,
    confidence character varying(12) NOT NULL,
    status character varying(12) NOT NULL,
    calibrated_at timestamp with time zone NOT NULL,
    valid_from date NOT NULL,
    review_after date NOT NULL,
    source_activity_id uuid,
    source_event_id uuid,
    proposal_id uuid,
    conditions text,
    notes text,
    supersedes_key character varying(40),
    CONSTRAINT ck_intensity_anchors_confidence CHECK (((confidence)::text = ANY ((ARRAY['high'::character varying, 'moderate'::character varying, 'low'::character varying, 'insufficient'::character varying])::text[]))),
    CONSTRAINT ck_intensity_anchors_kind CHECK (((kind)::text = ANY ((ARRAY['hr_aerobic_upper'::character varying, 'hr_threshold_lower'::character varying, 'speed_aerobic_upper'::character varying, 'speed_threshold_lower'::character varying, 'performance_5k'::character varying, 'performance_1mile'::character varying, 'performance_3min'::character varying, 'performance_20_30min'::character varying])::text[]))),
    CONSTRAINT ck_intensity_anchors_protocol CHECK (((protocol)::text = ANY ((ARRAY['race_5k'::character varying, 'time_trial_5k'::character varying, 'time_trial_1mile'::character varying, 'time_trial_3min'::character varying, 'time_trial_20_30min'::character varying, 'workout_derived'::character varying, 'lab_test'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_intensity_anchors_status CHECK (((status)::text = ANY ((ARRAY['provisional'::character varying, 'active'::character varying, 'expired'::character varying, 'invalid'::character varying])::text[]))),
    CONSTRAINT ck_intensity_anchors_unit CHECK (((unit)::text = ANY ((ARRAY['bpm'::character varying, 'mps'::character varying, 's'::character varying, 'm'::character varying])::text[]))),
    CONSTRAINT ck_intensity_anchors_unit_kind CHECK (((((kind)::text ~~ 'hr_%'::text) AND ((unit)::text = 'bpm'::text)) OR (((kind)::text ~~ 'speed_%'::text) AND ((unit)::text = 'mps'::text)) OR (((kind)::text = ANY ((ARRAY['performance_5k'::character varying, 'performance_1mile'::character varying])::text[])) AND ((unit)::text = 's'::text)) OR (((kind)::text = 'performance_3min'::text) AND ((unit)::text = 'm'::text)) OR (((kind)::text = 'performance_20_30min'::text) AND ((unit)::text = 'mps'::text)))),
    CONSTRAINT ck_intensity_anchors_value_high CHECK (((value_high IS NULL) OR (value_low <= value_high)))
);

CREATE TABLE public.legacy_import_map (
    id uuid NOT NULL,
    import_id uuid NOT NULL,
    source_table character varying(60) NOT NULL,
    source_id uuid NOT NULL,
    target_kind character varying(40) NOT NULL,
    target_id uuid,
    payload jsonb NOT NULL,
    payload_sha256 character varying(64) NOT NULL
);

CREATE TABLE public.legacy_import_runs (
    id uuid NOT NULL,
    key character varying(40) NOT NULL,
    source_fingerprint character varying(64) NOT NULL,
    imported_at timestamp with time zone NOT NULL,
    report jsonb NOT NULL,
    undo_payload jsonb
);

CREATE TABLE public.manual_sessions (
    id uuid NOT NULL,
    version integer NOT NULL,
    date date NOT NULL,
    "time" time without time zone,
    kind character varying(40) NOT NULL,
    duration_s double precision,
    effort integer,
    note text,
    linked_activity_id uuid,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.metric_configs (
    id uuid NOT NULL,
    metric_id character varying(60) NOT NULL,
    method_version character varying(40) NOT NULL,
    config jsonb NOT NULL,
    config_hash character varying(64) NOT NULL
);

CREATE TABLE public.metric_results (
    id uuid NOT NULL,
    metric_id character varying(60) NOT NULL,
    method_version character varying(40) NOT NULL,
    subject_type character varying(12) NOT NULL,
    subject_key character varying(120) NOT NULL,
    window_start timestamp with time zone,
    window_end timestamp with time zone,
    window_label character varying(40),
    status character varying(16) NOT NULL,
    quality_status character varying(14),
    value jsonb,
    unit character varying(16),
    reason_codes character varying(40)[] DEFAULT '{}'::character varying[] NOT NULL,
    quality_flags character varying(40)[] DEFAULT '{}'::character varying[] NOT NULL,
    source_refs jsonb NOT NULL,
    anchor_keys character varying(40)[] DEFAULT '{}'::character varying[] NOT NULL,
    config_hash character varying(64) NOT NULL,
    anchor_set_hash character varying(64),
    calculated_at timestamp with time zone NOT NULL,
    dependency_hash character varying(64) NOT NULL,
    timezone character varying(100) NOT NULL,
    is_current boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_metric_results_quality_status CHECK (((quality_status)::text = ANY ((ARRAY['good'::character varying, 'limited'::character varying, 'insufficient'::character varying])::text[]))),
    CONSTRAINT ck_metric_results_status CHECK (((status)::text = ANY ((ARRAY['available'::character varying, 'partial'::character varying, 'missing'::character varying, 'invalid'::character varying, 'not_applicable'::character varying, 'not_assessable'::character varying])::text[]))),
    CONSTRAINT ck_metric_results_subject_type CHECK (((subject_type)::text = ANY ((ARRAY['activity'::character varying, 'session'::character varying, 'window'::character varying, 'night'::character varying, 'report'::character varying])::text[])))
);

CREATE TABLE public.plan_versions (
    id uuid NOT NULL,
    version integer NOT NULL,
    parent_id uuid,
    status character varying(30) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    profile_version integer NOT NULL,
    anchor_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_at timestamp with time zone,
    reason text
);

CREATE TABLE public.planned_sessions (
    id uuid NOT NULL,
    plan_id uuid NOT NULL,
    date date NOT NULL,
    kind character varying(40) NOT NULL,
    target jsonb NOT NULL
);

CREATE TABLE public.profile_versions (
    id uuid NOT NULL,
    version integer NOT NULL,
    effective_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    timezone character varying(100) NOT NULL,
    cycle_anchor date,
    anchor_confirmed boolean NOT NULL,
    strength_days_confirmed boolean NOT NULL,
    scheduled_strength_days jsonb NOT NULL,
    facts jsonb NOT NULL,
    preferences jsonb NOT NULL,
    unknowns jsonb NOT NULL,
    strength_schedule_mode character varying(16) DEFAULT 'weekly'::character varying NOT NULL,
    strength_week_a_start date,
    strength_week_a_days jsonb DEFAULT '[]'::jsonb NOT NULL,
    strength_week_b_days jsonb DEFAULT '[]'::jsonb NOT NULL,
    mobility_week_a_days jsonb DEFAULT '[]'::jsonb NOT NULL,
    mobility_week_b_days jsonb DEFAULT '[]'::jsonb NOT NULL,
    mobility_optional_days jsonb DEFAULT '[]'::jsonb NOT NULL
);

CREATE TABLE public.prompts (
    id uuid NOT NULL,
    kind character varying(20) NOT NULL,
    activity_id uuid,
    session_uid uuid,
    opens_at timestamp with time zone NOT NULL,
    closes_at timestamp with time zone,
    status character varying(10) NOT NULL,
    CONSTRAINT ck_prompts_kind CHECK (((kind)::text = ANY ((ARRAY['rpe'::character varying, 'delayed_symptom'::character varying, 'unmatched_session'::character varying, 'missing_activity'::character varying])::text[]))),
    CONSTRAINT ck_prompts_status CHECK (((status)::text = ANY ((ARRAY['open'::character varying, 'answered'::character varying, 'dismissed'::character varying, 'expired'::character varying])::text[])))
);

CREATE TABLE public.raw_objects (
    id uuid NOT NULL,
    sha256 character varying(64) NOT NULL,
    relative_path text NOT NULL,
    byte_size integer NOT NULL,
    media_type character varying(120) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.recovery_observations (
    id uuid NOT NULL,
    source_account_id uuid NOT NULL,
    source_record_id uuid,
    metric character varying(50) NOT NULL,
    source_date date NOT NULL,
    time_semantics character varying(100) NOT NULL,
    value double precision NOT NULL,
    unit character varying(30) NOT NULL,
    statistic character varying(100) NOT NULL,
    source_revision character varying(100) NOT NULL
);

CREATE TABLE public.session_completions (
    id uuid NOT NULL,
    session_uid uuid NOT NULL,
    activity_id uuid,
    strong_workout_id uuid,
    manual_session_id uuid,
    status character varying(24) NOT NULL,
    match_method character varying(20) NOT NULL,
    modification_reason character varying(40),
    reason_note text,
    version integer DEFAULT 1 NOT NULL,
    input_version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_session_completions_match_method CHECK (((match_method)::text = ANY ((ARRAY['explicit'::character varying, 'auto_same_day'::character varying, 'confirmed_move'::character varying, 'user_marked'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT ck_session_completions_modification_reason CHECK (((modification_reason)::text = ANY ((ARRAY['symptom_onset'::character varying, 'fatigue'::character varying, 'illness'::character varying, 'schedule'::character varying, 'weather'::character varying, 'equipment'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT ck_session_completions_status CHECK (((status)::text = ANY ((ARRAY['completed_as_planned'::character varying, 'completed_modified'::character varying, 'partial'::character varying, 'moved'::character varying, 'skipped'::character varying, 'extra'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT ck_session_completions_status_subject CHECK ((((status)::text = ANY ((ARRAY['skipped'::character varying, 'unknown'::character varying])::text[])) OR (num_nonnulls(activity_id, strong_workout_id, manual_session_id) = 1) OR (((status)::text = 'completed_as_planned'::text) AND ((match_method)::text = 'user_marked'::text)))),
    CONSTRAINT ck_session_completions_subject CHECK ((num_nonnulls(activity_id, strong_workout_id, manual_session_id) <= 1))
);

CREATE TABLE public.session_rpe (
    id uuid NOT NULL,
    activity_id uuid,
    strong_workout_id uuid,
    manual_session_id uuid,
    rpe numeric(3,1) NOT NULL,
    source character varying(12) NOT NULL,
    collected_at timestamp with time zone NOT NULL,
    collection_delay_s integer,
    CONSTRAINT ck_session_rpe_rpe CHECK (((rpe IS NULL) OR ((rpe >= (0)::numeric) AND (rpe <= (10)::numeric)))),
    CONSTRAINT ck_session_rpe_source CHECK (((source)::text = ANY ((ARRAY['manual'::character varying, 'garmin_fit'::character varying])::text[]))),
    CONSTRAINT ck_session_rpe_subject CHECK ((num_nonnulls(activity_id, strong_workout_id, manual_session_id) = 1))
);

CREATE TABLE public.source_accounts (
    id uuid NOT NULL,
    provider character varying(40) NOT NULL,
    account_scope character varying(256) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.source_records (
    id uuid NOT NULL,
    source_account_id uuid NOT NULL,
    import_batch_id uuid,
    raw_object_id uuid,
    source_identity character varying(256) NOT NULL,
    payload_hash character varying(64) NOT NULL,
    fetched_at timestamp with time zone NOT NULL,
    source_modified_at timestamp with time zone,
    parser_version character varying(80) NOT NULL,
    source_kind character varying(50) NOT NULL,
    fields jsonb NOT NULL,
    rejected_reason character varying(100)
);

CREATE TABLE public.strength_routine_slots (
    id uuid NOT NULL,
    label character varying(40) NOT NULL,
    default_weekday smallint NOT NULL,
    lower_body_cost character varying(10) NOT NULL,
    typical_duration_s integer,
    main_lower_body_lifts text[] DEFAULT '{}'::text[] NOT NULL,
    active boolean DEFAULT true NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_strength_routine_slots_default_weekday CHECK (((default_weekday >= 0) AND (default_weekday <= 6))),
    CONSTRAINT ck_strength_routine_slots_lower_body_cost CHECK (((lower_body_cost)::text = ANY ((ARRAY['low'::character varying, 'moderate'::character varying, 'high'::character varying])::text[])))
);

CREATE TABLE public.strong_workouts (
    id uuid NOT NULL,
    source_account_id uuid NOT NULL,
    source_identity character varying(64) NOT NULL,
    source_record_id uuid NOT NULL,
    raw_object_id uuid NOT NULL,
    payload_hash character varying(64) NOT NULL,
    local_date date NOT NULL,
    local_start character varying(19) NOT NULL,
    workout_name text NOT NULL,
    duration_s double precision,
    sets jsonb NOT NULL,
    row_count integer NOT NULL,
    resolution_state character varying(30) DEFAULT 'resolved'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE public.symptom_reports (
    id uuid NOT NULL,
    checkin_id uuid NOT NULL,
    site character varying(60) NOT NULL,
    side character varying(10) NOT NULL,
    severity numeric(3,1) NOT NULL,
    timing character varying(20) NOT NULL,
    CONSTRAINT ck_symptom_reports_severity CHECK (((severity IS NULL) OR ((severity >= (0)::numeric) AND (severity <= (10)::numeric)))),
    CONSTRAINT ck_symptom_reports_side CHECK (((side)::text = ANY ((ARRAY['left'::character varying, 'right'::character varying, 'both'::character varying, 'na'::character varying])::text[]))),
    CONSTRAINT ck_symptom_reports_timing CHECK (((timing)::text = ANY ((ARRAY['during'::character varying, 'immediately_after'::character varying, 'next_morning'::character varying, 'hours_24_48'::character varying, 'later'::character varying, 'unknown'::character varying])::text[])))
);

CREATE TABLE public.sync_jobs (
    id uuid NOT NULL,
    dataset character varying(50) NOT NULL,
    start_date date,
    end_date date,
    status character varying(30) NOT NULL,
    checkpoint jsonb NOT NULL,
    counters jsonb NOT NULL,
    heartbeat_at timestamp with time zone,
    next_attempt_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    error_code character varying(100)
);

CREATE TABLE public.sync_state (
    dataset character varying(50) NOT NULL,
    last_attempt_at timestamp with time zone,
    last_success_at timestamp with time zone,
    newest_observation_at timestamp with time zone,
    requested_start date,
    requested_end date,
    fully_enumerated boolean NOT NULL,
    status character varying(40) NOT NULL,
    reason character varying(100)
);

CREATE TABLE public.trip_legs (
    id uuid NOT NULL,
    trip_id uuid NOT NULL,
    gcal_event_id uuid NOT NULL,
    leg_hash character varying(64) NOT NULL,
    seq smallint NOT NULL
);

CREATE TABLE public.trips (
    id uuid NOT NULL,
    status character varying(16) NOT NULL,
    start_date date NOT NULL,
    end_date date,
    destination_label character varying(120),
    destination_tz character varying(64) NOT NULL,
    source character varying(8) DEFAULT 'detected'::character varying NOT NULL,
    confidence character varying(8),
    running_access character varying(8),
    gym_access character varying(8),
    day_availability jsonb DEFAULT '[]'::jsonb NOT NULL,
    edited boolean DEFAULT false NOT NULL,
    detected jsonb NOT NULL,
    review_reason character varying(16),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    CONSTRAINT ck_trips_confidence CHECK (((confidence)::text = ANY ((ARRAY['high'::character varying, 'medium'::character varying, 'low'::character varying])::text[]))),
    CONSTRAINT ck_trips_dates CHECK (((end_date IS NULL) OR (end_date >= start_date))),
    CONSTRAINT ck_trips_gym_access CHECK (((gym_access)::text = ANY ((ARRAY['full'::character varying, 'limited'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT ck_trips_review_reason CHECK (((review_reason)::text = ANY ((ARRAY['source_changed'::character varying, 'source_removed'::character varying])::text[]))),
    CONSTRAINT ck_trips_review_status CHECK ((((status)::text = 'needs_review'::text) = (review_reason IS NOT NULL))),
    CONSTRAINT ck_trips_running_access CHECK (((running_access)::text = ANY ((ARRAY['normal'::character varying, 'limited'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT ck_trips_source CHECK (((source)::text = ANY ((ARRAY['detected'::character varying, 'manual'::character varying])::text[]))),
    CONSTRAINT ck_trips_source_shape CHECK (((((source)::text = 'detected'::text) AND (confidence IS NOT NULL)) OR (((source)::text = 'manual'::text) AND (confidence IS NULL) AND (end_date IS NOT NULL) AND ((status)::text <> 'needs_review'::text)))),
    CONSTRAINT ck_trips_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'confirmed'::character varying, 'dismissed'::character varying, 'needs_review'::character varying])::text[])))
);

CREATE TABLE public.weekly_snapshots (
    id uuid NOT NULL,
    week_start date NOT NULL,
    week_end date NOT NULL,
    schema_version character varying(30) NOT NULL,
    metric_version character varying(30) NOT NULL,
    data_revision integer NOT NULL,
    profile_version integer NOT NULL,
    plan_version integer NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    summary jsonb NOT NULL
);

ALTER TABLE ONLY public.app_state ALTER COLUMN id SET DEFAULT nextval('public.app_state_id_seq'::regclass);

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_source_account_id_garmin_id_key UNIQUE (source_account_id, garmin_id);

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_source_account_id_source_identity_key UNIQUE (source_account_id, source_identity);

ALTER TABLE ONLY public.activity_annotations
    ADD CONSTRAINT activity_annotations_activity_id_version_key UNIQUE (activity_id, version);

ALTER TABLE ONLY public.activity_annotations
    ADD CONSTRAINT activity_annotations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.activity_laps
    ADD CONSTRAINT activity_laps_activity_id_lap_index_key UNIQUE (activity_id, lap_index);

ALTER TABLE ONLY public.activity_laps
    ADD CONSTRAINT activity_laps_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.activity_sources
    ADD CONSTRAINT activity_sources_activity_id_source_record_id_key UNIQUE (activity_id, source_record_id);

ALTER TABLE ONLY public.activity_sources
    ADD CONSTRAINT activity_sources_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.activity_streams
    ADD CONSTRAINT activity_streams_pkey PRIMARY KEY (activity_id);

ALTER TABLE ONLY public.activity_workout_steps
    ADD CONSTRAINT activity_workout_steps_activity_id_message_index_key UNIQUE (activity_id, message_index);

ALTER TABLE ONLY public.activity_workout_steps
    ADD CONSTRAINT activity_workout_steps_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

ALTER TABLE ONLY public.app_state
    ADD CONSTRAINT app_state_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT block_benchmarks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.block_decisions
    ADD CONSTRAINT block_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.block_versions
    ADD CONSTRAINT block_versions_block_uid_version_key UNIQUE (block_uid, version);

ALTER TABLE ONLY public.block_versions
    ADD CONSTRAINT block_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT blocks_block_uid_key UNIQUE (block_uid);

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT blocks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.calendar_session_revisions
    ADD CONSTRAINT calendar_session_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.calendar_session_revisions
    ADD CONSTRAINT calendar_session_revisions_session_uid_revision_key UNIQUE (session_uid, revision);

ALTER TABLE ONLY public.calendar_versions
    ADD CONSTRAINT calendar_versions_number_key UNIQUE (number);

ALTER TABLE ONLY public.calendar_versions
    ADD CONSTRAINT calendar_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.checkin_revisions
    ADD CONSTRAINT checkin_revisions_checkin_id_version_key UNIQUE (checkin_id, version);

ALTER TABLE ONLY public.checkin_revisions
    ADD CONSTRAINT checkin_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.checkin_v2_revisions
    ADD CONSTRAINT checkin_v2_revisions_checkin_id_version_key UNIQUE (checkin_id, version);

ALTER TABLE ONLY public.checkin_v2_revisions
    ADD CONSTRAINT checkin_v2_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_idempotency_key_key UNIQUE (idempotency_key);

ALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.checkins_v2
    ADD CONSTRAINT checkins_v2_idempotency_key_key UNIQUE (idempotency_key);

ALTER TABLE ONLY public.checkins_v2
    ADD CONSTRAINT checkins_v2_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_chat_file_imports
    ADD CONSTRAINT coach_chat_file_imports_pkey PRIMARY KEY (mode);

ALTER TABLE ONLY public.coach_chat_receipts
    ADD CONSTRAINT coach_chat_receipts_pkey PRIMARY KEY (mode, client_message_id);

ALTER TABLE ONLY public.coach_chat_reviews
    ADD CONSTRAINT coach_chat_reviews_pkey PRIMARY KEY (mode, id);

ALTER TABLE ONLY public.coach_decision_keys
    ADD CONSTRAINT coach_decision_keys_pkey PRIMARY KEY (idempotency_key);

ALTER TABLE ONLY public.coach_outcome_events
    ADD CONSTRAINT coach_outcome_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_outcomes
    ADD CONSTRAINT coach_outcomes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_outcomes
    ADD CONSTRAINT coach_outcomes_recommendation_id_key UNIQUE (recommendation_id);

ALTER TABLE ONLY public.coach_plan_revisions
    ADD CONSTRAINT coach_plan_revisions_idempotency_key_key UNIQUE (idempotency_key);

ALTER TABLE ONLY public.coach_plan_revisions
    ADD CONSTRAINT coach_plan_revisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_plan_revisions
    ADD CONSTRAINT coach_plan_revisions_workflow_as_of_evidence_hash_key UNIQUE (workflow, as_of, evidence_hash);

ALTER TABLE ONLY public.coach_proposal_changes
    ADD CONSTRAINT coach_proposal_changes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_proposal_changes
    ADD CONSTRAINT coach_proposal_changes_proposal_id_change_id_key UNIQUE (proposal_id, change_id);

ALTER TABLE ONLY public.coach_proposal_revisions
    ADD CONSTRAINT coach_proposal_revisions_pkey PRIMARY KEY (proposal_id, revision);

ALTER TABLE ONLY public.coach_proposals
    ADD CONSTRAINT coach_proposals_decision_idempotency_key_key UNIQUE (decision_idempotency_key);

ALTER TABLE ONLY public.coach_proposals
    ADD CONSTRAINT coach_proposals_input_hash_key UNIQUE (input_hash);

ALTER TABLE ONLY public.coach_proposals
    ADD CONSTRAINT coach_proposals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_recommendations
    ADD CONSTRAINT coach_recommendations_kind_as_of_input_hash_key UNIQUE (kind, as_of, input_hash);

ALTER TABLE ONLY public.coach_recommendations
    ADD CONSTRAINT coach_recommendations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coach_snapshots
    ADD CONSTRAINT coach_snapshots_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_activity_id_key UNIQUE (activity_id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_manual_session_id_key UNIQUE (manual_session_id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_planned_session_id_activity_id_key UNIQUE (planned_session_id, activity_id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_planned_session_id_key UNIQUE (planned_session_id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_planned_session_id_manual_session_id_key UNIQUE (planned_session_id, manual_session_id);

ALTER TABLE ONLY public.conflicts
    ADD CONSTRAINT conflicts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.coverage_intervals
    ADD CONSTRAINT coverage_intervals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.exception_findings
    ADD CONSTRAINT exception_findings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.exception_patches
    ADD CONSTRAINT exception_patches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.exception_patches
    ADD CONSTRAINT exception_patches_proposal_id_key UNIQUE (proposal_id);

ALTER TABLE ONLY public.fit_files
    ADD CONSTRAINT fit_files_activity_id_key UNIQUE (activity_id);

ALTER TABLE ONLY public.fit_files
    ADD CONSTRAINT fit_files_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.fit_files
    ADD CONSTRAINT fit_files_raw_object_id_key UNIQUE (raw_object_id);

ALTER TABLE ONLY public.gcal_events
    ADD CONSTRAINT gcal_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.goals
    ADD CONSTRAINT goals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.import_batches
    ADD CONSTRAINT import_batches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.intensity_anchors
    ADD CONSTRAINT intensity_anchors_anchor_key_key UNIQUE (anchor_key);

ALTER TABLE ONLY public.intensity_anchors
    ADD CONSTRAINT intensity_anchors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.legacy_import_map
    ADD CONSTRAINT legacy_import_map_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.legacy_import_map
    ADD CONSTRAINT legacy_import_map_source_table_source_id_target_kind_key UNIQUE (source_table, source_id, target_kind);

ALTER TABLE ONLY public.legacy_import_runs
    ADD CONSTRAINT legacy_import_runs_key_key UNIQUE (key);

ALTER TABLE ONLY public.legacy_import_runs
    ADD CONSTRAINT legacy_import_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.manual_sessions
    ADD CONSTRAINT manual_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.metric_configs
    ADD CONSTRAINT metric_configs_metric_id_method_version_config_hash_key UNIQUE (metric_id, method_version, config_hash);

ALTER TABLE ONLY public.metric_configs
    ADD CONSTRAINT metric_configs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.metric_results
    ADD CONSTRAINT metric_results_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.plan_versions
    ADD CONSTRAINT plan_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.planned_sessions
    ADD CONSTRAINT planned_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.profile_versions
    ADD CONSTRAINT profile_versions_version_key UNIQUE (version);

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT prompts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.raw_objects
    ADD CONSTRAINT raw_objects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.raw_objects
    ADD CONSTRAINT raw_objects_sha256_key UNIQUE (sha256);

ALTER TABLE ONLY public.recovery_observations
    ADD CONSTRAINT recovery_observations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.recovery_observations
    ADD CONSTRAINT recovery_observations_source_account_id_metric_source_date__key UNIQUE (source_account_id, metric, source_date, statistic);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT session_completions_activity_id_key UNIQUE (activity_id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT session_completions_manual_session_id_key UNIQUE (manual_session_id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT session_completions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT session_completions_session_uid_key UNIQUE (session_uid);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT session_completions_strong_workout_id_key UNIQUE (strong_workout_id);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT session_rpe_activity_id_source_key UNIQUE (activity_id, source);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT session_rpe_manual_session_id_source_key UNIQUE (manual_session_id, source);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT session_rpe_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT session_rpe_strong_workout_id_source_key UNIQUE (strong_workout_id, source);

ALTER TABLE ONLY public.source_accounts
    ADD CONSTRAINT source_accounts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.source_accounts
    ADD CONSTRAINT source_accounts_provider_account_scope_key UNIQUE (provider, account_scope);

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_source_account_id_source_identity_payload_ha_key UNIQUE (source_account_id, source_identity, payload_hash);

ALTER TABLE ONLY public.strength_routine_slots
    ADD CONSTRAINT strength_routine_slots_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.strong_workouts
    ADD CONSTRAINT strong_workouts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.strong_workouts
    ADD CONSTRAINT strong_workouts_source_account_id_source_identity_key UNIQUE (source_account_id, source_identity);

ALTER TABLE ONLY public.symptom_reports
    ADD CONSTRAINT symptom_reports_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sync_jobs
    ADD CONSTRAINT sync_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sync_state
    ADD CONSTRAINT sync_state_pkey PRIMARY KEY (dataset);

ALTER TABLE ONLY public.trip_legs
    ADD CONSTRAINT trip_legs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.trips
    ADD CONSTRAINT trips_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT uq_block_benchmarks_block_version UNIQUE (block_uid, block_version);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT uq_completion_planned_session UNIQUE (planned_session_id);

ALTER TABLE ONLY public.events
    ADD CONSTRAINT uq_events_rank UNIQUE (rank) DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE ONLY public.gcal_events
    ADD CONSTRAINT uq_gcal_events_google_id UNIQUE (google_event_id);

ALTER TABLE ONLY public.trip_legs
    ADD CONSTRAINT uq_trip_legs_event UNIQUE (gcal_event_id);

ALTER TABLE ONLY public.trip_legs
    ADD CONSTRAINT uq_trip_legs_seq UNIQUE (trip_id, seq);

ALTER TABLE ONLY public.weekly_snapshots
    ADD CONSTRAINT weekly_snapshots_pkey PRIMARY KEY (id);

CREATE UNIQUE INDEX coach_chat_current ON public.coach_chat_reviews USING btree (mode) WHERE current;

CREATE INDEX ix_activities_local_date ON public.activities USING btree (local_date);

CREATE INDEX ix_activities_start_at ON public.activities USING btree (start_at);

CREATE INDEX ix_calendar_session_revisions_calendar_version_number ON public.calendar_session_revisions USING btree (calendar_version_number);

CREATE INDEX ix_calendar_session_revisions_local_date ON public.calendar_session_revisions USING btree (local_date);

CREATE INDEX ix_coach_outcome_events_recommendation_id ON public.coach_outcome_events USING btree (recommendation_id);

CREATE INDEX ix_coach_recommendations_as_of ON public.coach_recommendations USING btree (as_of);

CREATE INDEX ix_gcal_events_start_at ON public.gcal_events USING btree (start_at);

CREATE INDEX ix_gcal_events_start_date ON public.gcal_events USING btree (start_date);

CREATE INDEX ix_strong_workouts_local_date ON public.strong_workouts USING btree (local_date);

CREATE UNIQUE INDEX uq_coach_proposals_one_open ON public.coach_proposals USING btree ((true)) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'stale'::character varying, 'invalid'::character varying])::text[]));

CREATE UNIQUE INDEX uq_exception_findings_active ON public.exception_findings USING btree (rule_code, entity_key) WHERE ((status)::text = ANY ((ARRAY['open'::character varying, 'addressed'::character varying])::text[]));

CREATE UNIQUE INDEX uq_metric_results_current ON public.metric_results USING btree (metric_id, method_version, subject_key) WHERE is_current;

CREATE UNIQUE INDEX uq_metric_results_identity ON public.metric_results USING btree (metric_id, method_version, subject_key, config_hash, COALESCE(anchor_set_hash, ''::character varying), dependency_hash);

CREATE UNIQUE INDEX uq_prompts_kind_activity_session ON public.prompts USING btree (kind, activity_id, session_uid) NULLS NOT DISTINCT;

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_source_account_id_fkey FOREIGN KEY (source_account_id) REFERENCES public.source_accounts(id);

ALTER TABLE ONLY public.activity_annotations
    ADD CONSTRAINT activity_annotations_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.activity_sources
    ADD CONSTRAINT activity_sources_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.activity_sources
    ADD CONSTRAINT activity_sources_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES public.source_records(id);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT block_benchmarks_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT block_benchmarks_block_uid_fkey FOREIGN KEY (block_uid) REFERENCES public.blocks(block_uid);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT block_benchmarks_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.events(id);

ALTER TABLE ONLY public.block_benchmarks
    ADD CONSTRAINT block_benchmarks_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.block_versions
    ADD CONSTRAINT block_versions_target_event_id_fkey FOREIGN KEY (target_event_id) REFERENCES public.events(id);

ALTER TABLE ONLY public.checkin_revisions
    ADD CONSTRAINT checkin_revisions_checkin_id_fkey FOREIGN KEY (checkin_id) REFERENCES public.checkins(id);

ALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.coach_outcome_events
    ADD CONSTRAINT coach_outcome_events_recommendation_id_fkey FOREIGN KEY (recommendation_id) REFERENCES public.coach_recommendations(id);

ALTER TABLE ONLY public.coach_outcomes
    ADD CONSTRAINT coach_outcomes_recommendation_id_fkey FOREIGN KEY (recommendation_id) REFERENCES public.coach_recommendations(id);

ALTER TABLE ONLY public.coach_plan_revisions
    ADD CONSTRAINT coach_plan_revisions_parent_revision_id_fkey FOREIGN KEY (parent_revision_id) REFERENCES public.coach_plan_revisions(id);

ALTER TABLE ONLY public.coach_plan_revisions
    ADD CONSTRAINT coach_plan_revisions_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plan_versions(id);

ALTER TABLE ONLY public.coach_proposal_revisions
    ADD CONSTRAINT coach_proposal_revisions_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_activity_id_fkey FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_manual_session_id_fkey FOREIGN KEY (manual_session_id) REFERENCES public.manual_sessions(id);

ALTER TABLE ONLY public.completion_links
    ADD CONSTRAINT completion_links_planned_session_id_fkey FOREIGN KEY (planned_session_id) REFERENCES public.planned_sessions(id);

ALTER TABLE ONLY public.conflicts
    ADD CONSTRAINT conflicts_manual_session_id_fkey FOREIGN KEY (manual_session_id) REFERENCES public.manual_sessions(id);

ALTER TABLE ONLY public.exception_findings
    ADD CONSTRAINT exception_findings_patch_id_fkey FOREIGN KEY (patch_id) REFERENCES public.exception_patches(id);

ALTER TABLE ONLY public.exception_findings
    ADD CONSTRAINT exception_findings_reviewed_by_proposal_id_fkey FOREIGN KEY (reviewed_by_proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.exception_patches
    ADD CONSTRAINT exception_patches_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT fk_activities_fit_file_id FOREIGN KEY (fit_file_id) REFERENCES public.fit_files(id);

ALTER TABLE ONLY public.activity_laps
    ADD CONSTRAINT fk_activity_laps_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.activity_streams
    ADD CONSTRAINT fk_activity_streams_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.activity_workout_steps
    ADD CONSTRAINT fk_activity_workout_steps_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.block_decisions
    ADD CONSTRAINT fk_block_decisions_block_uid FOREIGN KEY (block_uid) REFERENCES public.blocks(block_uid);

ALTER TABLE ONLY public.block_decisions
    ADD CONSTRAINT fk_block_decisions_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.block_versions
    ADD CONSTRAINT fk_block_versions_block_uid FOREIGN KEY (block_uid) REFERENCES public.blocks(block_uid);

ALTER TABLE ONLY public.block_versions
    ADD CONSTRAINT fk_block_versions_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.calendar_session_revisions
    ADD CONSTRAINT fk_calendar_session_revisions_calendar_version_number FOREIGN KEY (calendar_version_number) REFERENCES public.calendar_versions(number);

ALTER TABLE ONLY public.calendar_session_revisions
    ADD CONSTRAINT fk_calendar_session_revisions_strength_slot_id FOREIGN KEY (strength_slot_id) REFERENCES public.strength_routine_slots(id);

ALTER TABLE ONLY public.calendar_versions
    ADD CONSTRAINT fk_calendar_versions_block_version_id FOREIGN KEY (block_version_id) REFERENCES public.block_versions(id);

ALTER TABLE ONLY public.calendar_versions
    ADD CONSTRAINT fk_calendar_versions_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.checkin_v2_revisions
    ADD CONSTRAINT fk_checkin_v2_revisions_checkin_id FOREIGN KEY (checkin_id) REFERENCES public.checkins_v2(id);

ALTER TABLE ONLY public.checkins_v2
    ADD CONSTRAINT fk_checkins_v2_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.checkins_v2
    ADD CONSTRAINT fk_checkins_v2_prompt_id FOREIGN KEY (prompt_id) REFERENCES public.prompts(id);

ALTER TABLE ONLY public.coach_decision_keys
    ADD CONSTRAINT fk_coach_decision_keys_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.coach_proposal_changes
    ADD CONSTRAINT fk_coach_proposal_changes_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.coach_proposals
    ADD CONSTRAINT fk_coach_proposals_base_block_version_id FOREIGN KEY (base_block_version_id) REFERENCES public.block_versions(id);

ALTER TABLE ONLY public.coach_proposals
    ADD CONSTRAINT fk_coach_proposals_snapshot_id FOREIGN KEY (snapshot_id) REFERENCES public.coach_snapshots(id);

ALTER TABLE ONLY public.coach_snapshots
    ADD CONSTRAINT fk_coach_snapshots_block_version_id FOREIGN KEY (block_version_id) REFERENCES public.block_versions(id);

ALTER TABLE ONLY public.fit_files
    ADD CONSTRAINT fk_fit_files_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.fit_files
    ADD CONSTRAINT fk_fit_files_raw_object_id FOREIGN KEY (raw_object_id) REFERENCES public.raw_objects(id);

ALTER TABLE ONLY public.intensity_anchors
    ADD CONSTRAINT fk_intensity_anchors_proposal_id FOREIGN KEY (proposal_id) REFERENCES public.coach_proposals(id);

ALTER TABLE ONLY public.intensity_anchors
    ADD CONSTRAINT fk_intensity_anchors_source_activity_id FOREIGN KEY (source_activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.intensity_anchors
    ADD CONSTRAINT fk_intensity_anchors_source_event_id FOREIGN KEY (source_event_id) REFERENCES public.events(id);

ALTER TABLE ONLY public.legacy_import_map
    ADD CONSTRAINT fk_legacy_import_map_import_id FOREIGN KEY (import_id) REFERENCES public.legacy_import_runs(id);

ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT fk_prompts_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT fk_session_completions_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT fk_session_completions_manual_session_id FOREIGN KEY (manual_session_id) REFERENCES public.manual_sessions(id);

ALTER TABLE ONLY public.session_completions
    ADD CONSTRAINT fk_session_completions_strong_workout_id FOREIGN KEY (strong_workout_id) REFERENCES public.strong_workouts(id);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT fk_session_rpe_activity_id FOREIGN KEY (activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT fk_session_rpe_manual_session_id FOREIGN KEY (manual_session_id) REFERENCES public.manual_sessions(id);

ALTER TABLE ONLY public.session_rpe
    ADD CONSTRAINT fk_session_rpe_strong_workout_id FOREIGN KEY (strong_workout_id) REFERENCES public.strong_workouts(id);

ALTER TABLE ONLY public.symptom_reports
    ADD CONSTRAINT fk_symptom_reports_checkin_id FOREIGN KEY (checkin_id) REFERENCES public.checkins_v2(id);

ALTER TABLE ONLY public.manual_sessions
    ADD CONSTRAINT manual_sessions_linked_activity_id_fkey FOREIGN KEY (linked_activity_id) REFERENCES public.activities(id);

ALTER TABLE ONLY public.plan_versions
    ADD CONSTRAINT plan_versions_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.plan_versions(id);

ALTER TABLE ONLY public.planned_sessions
    ADD CONSTRAINT planned_sessions_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES public.plan_versions(id);

ALTER TABLE ONLY public.recovery_observations
    ADD CONSTRAINT recovery_observations_source_account_id_fkey FOREIGN KEY (source_account_id) REFERENCES public.source_accounts(id);

ALTER TABLE ONLY public.recovery_observations
    ADD CONSTRAINT recovery_observations_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES public.source_records(id);

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_import_batch_id_fkey FOREIGN KEY (import_batch_id) REFERENCES public.import_batches(id);

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_raw_object_id_fkey FOREIGN KEY (raw_object_id) REFERENCES public.raw_objects(id);

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_source_account_id_fkey FOREIGN KEY (source_account_id) REFERENCES public.source_accounts(id);

ALTER TABLE ONLY public.strong_workouts
    ADD CONSTRAINT strong_workouts_raw_object_id_fkey FOREIGN KEY (raw_object_id) REFERENCES public.raw_objects(id);

ALTER TABLE ONLY public.strong_workouts
    ADD CONSTRAINT strong_workouts_source_account_id_fkey FOREIGN KEY (source_account_id) REFERENCES public.source_accounts(id);

ALTER TABLE ONLY public.strong_workouts
    ADD CONSTRAINT strong_workouts_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES public.source_records(id);

ALTER TABLE ONLY public.trip_legs
    ADD CONSTRAINT trip_legs_gcal_event_id_fkey FOREIGN KEY (gcal_event_id) REFERENCES public.gcal_events(id);

ALTER TABLE ONLY public.trip_legs
    ADD CONSTRAINT trip_legs_trip_id_fkey FOREIGN KEY (trip_id) REFERENCES public.trips(id) ON DELETE CASCADE;
