from app.domain.sports import RUN_SPORTS
from app.metrics import volume


def test_volume_config_lists_exactly_the_run_sports():
    assert set(volume.CONFIG["sports"]) == RUN_SPORTS
