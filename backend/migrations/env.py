from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.agent_models  # noqa: F401
import app.calendar_models  # noqa: F401
import app.checkin_models  # noqa: F401
import app.coach_v2_models  # noqa: F401
import app.coaching_models  # noqa: F401
import app.fit_models  # noqa: F401
import app.metric_models  # noqa: F401
import app.models  # noqa: F401
import app.planning_models  # noqa: F401
import app.strong_models  # noqa: F401
from app.config import settings
from app.db import Base

config = context.config
config.set_main_option('sqlalchemy.url', settings.database_url.replace('%', '%%'))
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    supplied_connection = config.attributes.get('connection')
    if supplied_connection is not None:
        context.configure(connection=supplied_connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix='sqlalchemy.', poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
