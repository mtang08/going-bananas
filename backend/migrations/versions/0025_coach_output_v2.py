"""Coach output v2: typed proposal and block text, session briefs; earlier prose moves to legacy_text."""

import sqlalchemy as sa
from alembic import op

revision = "0025_coach_output_v2"
down_revision = "0024_google_calendar"
branch_labels = None
depends_on = None

# strip_ids mirrors contracts §4 ID_TOKEN (\m and \M are PostgreSQL word boundaries; \b is backspace),
# then tidies like the old frontend stripReferenceIds. strip_prose applies it to string values under
# the §4 PROSE_KEYS plus "notes" (old proposal change rows), recursing like _id_in_text.
STRIP_FUNCTIONS = (
    r"""CREATE OR REPLACE FUNCTION pg_temp.strip_ids(t text) RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $f$
      SELECT CASE WHEN t ~ p.id THEN btrim(
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(t,
          p.id, '', 'g'),
          '\[\s*[,;·\s]*\]', '', 'g'),
          '\(\s*[,;·\s]*\)', '', 'g'),
          '[ \t]+([.,;:])', '\1', 'g'),
          '[ \t]{2,}', ' ', 'g'),
        E' \t\n\r') ELSE t END
      FROM (VALUES ('\m(E-[A-Z]{2,8}-\d{2}|P\d{3}|REC\d{3}|S\d{3})\M'
                    '|\m[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\M')) AS p(id)
    $f$""",
    """CREATE OR REPLACE FUNCTION pg_temp.strip_ids_each(a text[]) RETURNS text[] LANGUAGE sql IMMUTABLE STRICT AS $f$
      SELECT ARRAY(SELECT pg_temp.strip_ids(x) FROM unnest(a) WITH ORDINALITY AS u(x, n) ORDER BY n)
    $f$""",
    """CREATE OR REPLACE FUNCTION pg_temp.strip_prose(j jsonb, prose boolean DEFAULT false) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE STRICT AS $f$
    BEGIN
      IF jsonb_typeof(j) = 'object' THEN
        RETURN COALESCE((SELECT jsonb_object_agg(key, pg_temp.strip_prose(value, key = ANY (ARRAY[
          'headline', 'text', 'when', 'then', 'check', 'coach_note', 'uncertainty', 'reason', 'intent', 'feel',
          'focus', 'why', 'effort_cue', 'objective', 'maintained_qualities', 'non_goals', 'early_review_triggers',
          'label', 'progress_when', 'protocol', 'progress_if', 'consolidate_if', 'emphasis', 'conditions',
          'triggering_evidence', 'relevant_context', 'monitor', 'return_criteria', 'escalate_criteria', 'pacing',
          'effort_and_limiter', 'symptoms', 'recovery_observation', 'training_implication', 'compared_with', 'note',
          'notes']))) FROM jsonb_each(j)), '{}');
      ELSIF jsonb_typeof(j) = 'array' THEN
        RETURN COALESCE((SELECT jsonb_agg(pg_temp.strip_prose(value, prose) ORDER BY n)
          FROM jsonb_array_elements(j) WITH ORDINALITY AS e(value, n)), '[]');
      ELSIF prose AND jsonb_typeof(j) = 'string' THEN
        RETURN to_jsonb(pg_temp.strip_ids(j #>> '{}'));
      END IF;
      RETURN j;
    END
    $f$""",
)

UPGRADE = (
    "ALTER TABLE coach_proposals RENAME COLUMN summary TO headline",
    """ALTER TABLE coach_proposals
        ADD COLUMN why jsonb NOT NULL DEFAULT '[]',
        ADD COLUMN uncertainty jsonb NOT NULL DEFAULT '[]',
        ADD COLUMN change_triggers jsonb NOT NULL DEFAULT '[]',
        ADD COLUMN next_check jsonb,
        ADD COLUMN coach_note text,
        ADD COLUMN legacy_text text""",
    r"""UPDATE coach_proposals SET legacy_text = NULLIF(concat_ws(E'\n\n',
        NULLIF(rationale, ''),
        'Next check-in: ' || NULLIF(follow_up, ''),
        'Block rationale: ' || NULLIF(block_change->'version_fields'->>'rationale', ''),
        (SELECT 'Completion indicators:' || string_agg(E'\n- ' || v, '')
           FROM jsonb_array_elements_text(COALESCE(block_change->'version_fields'->'completion_indicators', '[]')) AS v)
    ), '')""",
    """UPDATE coach_proposals SET block_change = jsonb_set(jsonb_set(
        block_change #- '{version_fields,rationale}' #- '{version_fields,completion_indicators}',
        '{version_fields,why}', '[]'), '{version_fields,indicators}', '[]')
      WHERE jsonb_typeof(block_change) = 'object'""",
    "ALTER TABLE coach_proposals DROP COLUMN rationale, DROP COLUMN follow_up",
    """UPDATE coach_proposals SET status = 'discarded', discarded_at = CURRENT_TIMESTAMP
      WHERE status IN ('pending', 'stale', 'invalid')""",
    """ALTER TABLE block_versions
        ADD COLUMN why jsonb NOT NULL DEFAULT '[]',
        ADD COLUMN indicators jsonb NOT NULL DEFAULT '[]',
        ADD COLUMN legacy_text text""",
    r"""UPDATE block_versions SET legacy_text = NULLIF(concat_ws(E'\n\n',
        NULLIF(rationale, ''),
        CASE WHEN cardinality(completion_indicators) > 0
             THEN 'Completion indicators:' || E'\n- ' || array_to_string(completion_indicators, E'\n- ') END
    ), '')""",
    "ALTER TABLE block_versions DROP COLUMN rationale, DROP COLUMN completion_indicators",
    "ALTER TABLE calendar_session_revisions ADD COLUMN brief jsonb",
    "UPDATE calendar_session_revisions SET notes = NULL WHERE notes IS NOT NULL",
    *STRIP_FUNCTIONS,
    """UPDATE coach_proposals SET headline = pg_temp.strip_ids(headline), legacy_text = pg_temp.strip_ids(legacy_text),
        block_change = pg_temp.strip_prose(block_change)""",
    # U12: the app shows these three payload sections; every other payload key stays as submitted.
    """UPDATE coach_proposals SET payload = payload || (
        SELECT COALESCE(jsonb_object_agg(key, pg_temp.strip_prose(value)), '{}') FROM jsonb_each(payload)
        WHERE key IN ('exception', 'event_review', 'patch_resolutions'))""",
    """UPDATE coach_proposal_changes SET reason = pg_temp.strip_ids(reason),
        before = CASE WHEN jsonb_typeof(before) = 'object' THEN pg_temp.strip_prose(before) - 'notes' ELSE before END,
        after = CASE WHEN jsonb_typeof(after) = 'object' THEN pg_temp.strip_prose(after) - 'notes' ELSE after END""",
    "UPDATE coach_proposal_revisions SET reason = pg_temp.strip_ids(reason)",
    """UPDATE block_versions SET objective = pg_temp.strip_ids(objective),
        maintained_qualities = pg_temp.strip_ids_each(maintained_qualities),
        non_goals = pg_temp.strip_ids_each(non_goals),
        early_review_triggers = pg_temp.strip_ids_each(early_review_triggers),
        constraints = pg_temp.strip_prose(constraints), benchmark = pg_temp.strip_prose(benchmark),
        build_outline = pg_temp.strip_prose(build_outline), legacy_text = pg_temp.strip_ids(legacy_text)""",
    "UPDATE block_benchmarks SET protocol = pg_temp.strip_ids(protocol)",
    """UPDATE calendar_session_revisions SET intent = pg_temp.strip_ids(intent),
        structure = pg_temp.strip_prose(structure)""",
    "UPDATE calendar_versions SET reason = pg_temp.strip_ids(reason) WHERE kind = 'proposal_accept'",
    "DROP FUNCTION pg_temp.strip_prose(jsonb, boolean), pg_temp.strip_ids_each(text[]), pg_temp.strip_ids(text)",
)

V2_DATA_PROBES = (
    "SELECT EXISTS (SELECT 1 FROM coach_proposals WHERE payload->>'schema_version' = 'coach_proposal.v2')",
    "SELECT EXISTS (SELECT 1 FROM block_versions WHERE why <> '[]'::jsonb OR indicators <> '[]'::jsonb)",
    "SELECT EXISTS (SELECT 1 FROM calendar_session_revisions WHERE jsonb_typeof(brief) = 'object')",
)

DOWNGRADE = (
    "ALTER TABLE calendar_session_revisions DROP COLUMN brief",
    "ALTER TABLE block_versions ADD COLUMN rationale text, ADD COLUMN completion_indicators text[] NOT NULL DEFAULT '{}'",
    "UPDATE block_versions SET rationale = COALESCE(legacy_text, '')",
    "ALTER TABLE block_versions ALTER COLUMN rationale SET NOT NULL",
    "ALTER TABLE block_versions DROP COLUMN why, DROP COLUMN indicators, DROP COLUMN legacy_text",
    "ALTER TABLE coach_proposals ADD COLUMN rationale text, ADD COLUMN follow_up text",
    "UPDATE coach_proposals SET rationale = COALESCE(payload->>'rationale', ''), follow_up = payload->>'follow_up'",
    "UPDATE coach_proposals SET block_change = payload->'block_change' WHERE jsonb_typeof(block_change) = 'object'",
    "ALTER TABLE coach_proposals ALTER COLUMN rationale SET NOT NULL",
    """ALTER TABLE coach_proposals DROP COLUMN why, DROP COLUMN uncertainty, DROP COLUMN change_triggers,
        DROP COLUMN next_check, DROP COLUMN coach_note, DROP COLUMN legacy_text""",
    "ALTER TABLE coach_proposals RENAME COLUMN headline TO summary",
)


def upgrade():
    for statement in UPGRADE:
        op.execute(statement)


def downgrade():
    # Refuse only when v2 data would be lost; restore the pre-migration backup instead.
    bind = op.get_bind()
    if any(bind.execute(sa.text(probe)).scalar() for probe in V2_DATA_PROBES):
        raise RuntimeError("restore_required_coach_output_v2")
    for statement in DOWNGRADE:
        op.execute(statement)
