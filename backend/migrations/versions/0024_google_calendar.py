"""Google Calendar events, trips, and trip legs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_google_calendar"
down_revision = "0023_treadmill_interval_paces"
branch_labels = None
depends_on = None

EMPTY = sa.text("'[]'::jsonb")
CATEGORIES = "('flight','lodging','ground_travel','reservation','out_of_office','appointment','work','social','other')"
TIME_SHAPE = (
    "(all_day AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NULL AND end_at IS NULL) OR "
    "(NOT all_day AND start_at IS NOT NULL AND end_at IS NOT NULL AND start_date IS NULL AND end_date IS NULL)"
)
SOURCE_SHAPE = (
    "(source = 'detected' AND confidence IS NOT NULL) OR "
    "(source = 'manual' AND confidence IS NULL AND end_date IS NOT NULL AND status <> 'needs_review')"
)


def upgrade():
    op.create_table(
        "gcal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("google_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("google_status", sa.String(12), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("location_codes", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("start_tz", sa.String(64)),
        sa.Column("end_tz", sa.String(64)),
        sa.Column("transparency", sa.String(12), nullable=False),
        sa.Column("response_status", sa.String(12)),
        sa.Column("busy", sa.Boolean(), nullable=False),
        sa.Column("flight_code", sa.String(8)),
        sa.Column("destination_label", sa.String(120)),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("auto_category", sa.String(16), nullable=False),
        sa.Column("category_source", sa.String(8), nullable=False),
        sa.Column("flight_confidence", sa.String(8)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("google_updated_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("google_event_id", name="uq_gcal_events_google_id"),
        sa.CheckConstraint("google_status IN ('confirmed','tentative')", name="ck_gcal_events_status"),
        sa.CheckConstraint("transparency IN ('opaque','transparent')", name="ck_gcal_events_transparency"),
        sa.CheckConstraint(
            "response_status IN ('needsAction','declined','tentative','accepted')", name="ck_gcal_events_response"
        ),
        sa.CheckConstraint(f"category IN {CATEGORIES}", name="ck_gcal_events_category"),
        sa.CheckConstraint(f"auto_category IN {CATEGORIES}", name="ck_gcal_events_auto_category"),
        sa.CheckConstraint("category_source IN ('auto','athlete')", name="ck_gcal_events_category_source"),
        sa.CheckConstraint("flight_confidence IN ('high','medium')", name="ck_gcal_events_flight_confidence"),
        sa.CheckConstraint(TIME_SHAPE, name="ck_gcal_events_time_shape"),
    )
    op.create_index("ix_gcal_events_start_at", "gcal_events", ["start_at"])
    op.create_index("ix_gcal_events_start_date", "gcal_events", ["start_date"])
    op.create_table(
        "trips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("destination_label", sa.String(120)),
        sa.Column("destination_tz", sa.String(64), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="detected"),
        sa.Column("confidence", sa.String(8)),
        sa.Column("running_access", sa.String(8)),
        sa.Column("gym_access", sa.String(8)),
        sa.Column("day_availability", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("detected", postgresql.JSONB(), nullable=False),
        sa.Column("review_reason", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("status IN ('pending','confirmed','dismissed','needs_review')", name="ck_trips_status"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_trips_dates"),
        sa.CheckConstraint("source IN ('detected','manual')", name="ck_trips_source"),
        sa.CheckConstraint("confidence IN ('high','medium','low')", name="ck_trips_confidence"),
        sa.CheckConstraint(SOURCE_SHAPE, name="ck_trips_source_shape"),
        sa.CheckConstraint("running_access IN ('normal','limited','none')", name="ck_trips_running_access"),
        sa.CheckConstraint("gym_access IN ('full','limited','none')", name="ck_trips_gym_access"),
        sa.CheckConstraint("review_reason IN ('source_changed','source_removed')", name="ck_trips_review_reason"),
        sa.CheckConstraint("(status = 'needs_review') = (review_reason IS NOT NULL)", name="ck_trips_review_status"),
    )
    op.create_table(
        "trip_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("gcal_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gcal_events.id"), nullable=False),
        sa.Column("leg_hash", sa.String(64), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("gcal_event_id", name="uq_trip_legs_event"),
        sa.UniqueConstraint("trip_id", "seq", name="uq_trip_legs_seq"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gcal_events) OR EXISTS (SELECT 1 FROM trips)")).scalar():
        raise RuntimeError("restore_required_nonempty_google_calendar")
    op.drop_table("trip_legs")
    op.drop_table("trips")
    op.drop_table("gcal_events")
