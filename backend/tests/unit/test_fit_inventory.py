from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures' / 'fit'))
from synthetic import LAT_CANARY, build_synthetic_zip  # noqa: E402

from app.adapters.garmin.fit import decode_fit_zip  # noqa: E402
from app.services.fit_inventory import build_inventory, collect_inventory, merge_key_paths  # noqa: E402


def test_recursive_shapes_and_redaction():
    shape = {'2026-11-12': [{'123': {'distance': 5, 'position_lat': LAT_CANARY,
        'startLat': LAT_CANARY, 'endLon': LAT_CANARY,
        'access_token': 'canary-secret', 'nested': [None, True, 2.5]}}]}
    paths = merge_key_paths([shape])
    assert '<key>[]' in paths
    assert '<key>[].<key>.nested[]' in paths
    serialized = json.dumps(paths)
    assert str(LAT_CANARY) not in serialized
    assert 'position_lat' not in serialized
    assert 'startLat' not in serialized and 'endLon' not in serialized
    assert 'access_token' not in serialized
    assert 'canary-secret' not in serialized


def test_synthetic_inventory_and_source_injection():
    data = build_synthetic_zip()
    decoded = decode_fit_zip(data)
    detail = {'activityId': '123456789', 'position_lat': LAT_CANARY}
    inventory = build_inventory(decoded, {'detail': detail})
    assert inventory['schema_version'] == 'fit_inventory.v1'
    assert inventory['message_counts']['record_mesgs'] == 588
    assert inventory['record_interval_s'] == {'count': 587, 'min': 1, 'median': 1, 'max': 13,
        'gaps_over_10s': 1}
    assert inventory['timer_segments'] == [[0, 300], [312, 600]]
    assert inventory['presence']['heart_rate'] is True
    assert str(LAT_CANARY) not in json.dumps(inventory)
    source = SimpleNamespace(download_activity=lambda id: data,
        activity_detail=lambda id: detail,
        activity_workouts=lambda id: [{'step': 1, 'serialNumber': 'private'}])
    collected = collect_inventory(source, ['synthetic-id'])
    assert collected['activities'][0]['message_counts']['record_mesgs'] == 588
    assert 'serialNumber' not in json.dumps(collected)
