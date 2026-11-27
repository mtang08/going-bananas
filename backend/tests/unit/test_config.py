import pytest

from app.config import Settings


def test_mode_database_suffix_guard():
    with pytest.raises(ValueError, match="APP_MODE suffix"):
        Settings(database_url="postgresql+psycopg://u:p@localhost/garmin_demo", app_mode="real")
    Settings(database_url="postgresql+psycopg://u:p@localhost/garmin_real", app_mode="real")


def test_settings_read_environment_on_construction(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/garmin_test")
    monkeypatch.setenv("PRIVATE_DIR", str(tmp_path))
    s = Settings()
    assert s.app_mode == "test"
    assert s.private_dir == tmp_path.resolve()
