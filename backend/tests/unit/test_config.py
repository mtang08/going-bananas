import pytest

from app.config import Settings


def test_mode_database_suffix_guard():
    with pytest.raises(ValueError, match='APP_MODE suffix'):
        Settings(database_url='postgresql+psycopg://u:p@localhost/garmin_demo', app_mode='real')
    Settings(database_url='postgresql+psycopg://u:p@localhost/garmin_real', app_mode='real')
