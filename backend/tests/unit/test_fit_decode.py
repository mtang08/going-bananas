from __future__ import annotations

import copy
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures' / 'fit'))
from synthetic import FIT_EPOCH_OFFSET, LAT_CANARY, START_FIT_TS, build_synthetic_fit, build_synthetic_zip  # noqa: E402

from app.adapters.garmin.fit import (  # noqa: E402
    FitDecodeError,
    decode_fit,
    decode_fit_zip,
    extract_fit,
)
from app.adapters.garmin.personal import GarminConfigurationError, GarminPersonalSource  # noqa: E402


def _code(call, expected):
    with pytest.raises(FitDecodeError) as error:
        call()
    assert error.value.code == expected


def test_synthetic_contract_and_privacy():
    decoded = decode_fit_zip(build_synthetic_zip())
    assert decoded.profile_version == '21221'
    assert decoded.sdk_version == '21.221.0'
    assert decoded.session.start_at == datetime.fromtimestamp(START_FIT_TS + FIT_EPOCH_OFFSET, UTC)
    assert (decoded.session.timer_s, decoded.session.distance_m, decoded.session.workout_rpe,
            decoded.session.workout_feel) == (588, 1764, 6.5, 75)
    assert decoded.message_inventory == {'file_id_mesgs': 1, 'event_mesgs': 4,
        'record_mesgs': 588, 'lap_mesgs': 2, 'session_mesgs': 1, 'workout_step_mesgs': 4}
    assert [lap.distance_m for lap in decoded.laps] == [900, 864]
    assert [lap.lap_trigger for lap in decoded.laps] == ['manual', 'session_end']
    assert [lap.wkt_step_index for lap in decoded.laps] == [0, 1]
    assert decoded.stream.sample_count == 588
    assert decoded.stream.max_gap_s == 13
    assert decoded.stream.timer_on == ((0, 300), (312, 600))
    assert decoded.steps[0].duration_value == 300
    assert decoded.steps[1].duration_value == 800
    assert (decoded.steps[1].target_low, decoded.steps[1].target_high) == (3.2, 3.6)
    assert (decoded.steps[2].repeat_from, decoded.steps[2].repeat_count) == (1, 4)
    assert (decoded.steps[3].target_low, decoded.steps[3].target_high) == (130, 145)
    serialized = json.dumps(decoded.field_names) + json.dumps(decoded.device)
    assert str(LAT_CANARY) not in serialized
    assert 'position_lat' not in serialized
    assert 'serial' not in serialized


def test_zip_and_crc_errors():
    _code(lambda: extract_fit(b'not a ZIP'), 'bad_zip')
    _code(lambda: extract_fit(build_synthetic_zip({'readme.txt': b'x'})), 'zip_member_count')
    _code(lambda: extract_fit(build_synthetic_zip({'a.fit': b'a', 'B.FIT': b'b'})), 'zip_member_count')
    _code(lambda: decode_fit(b'not FIT'), 'invalid_fit')
    corrupted = bytearray(build_synthetic_fit())
    corrupted[-3] ^= 1
    _code(lambda: decode_fit(bytes(corrupted)), 'invalid_crc')


def test_sdk_probes_are_fresh_and_read_flags_are_explicit(monkeypatch):
    from garmin_fit_sdk import Decoder as SDKDecoder

    from app.adapters.garmin import fit

    calls = []
    instances = []
    class TrackingDecoder(SDKDecoder):
        def __init__(self, stream):
            super().__init__(stream)
            instances.append(self)
        def is_fit(self):
            calls.append(('is_fit', id(self)))
            return super().is_fit()
        def check_integrity(self):
            calls.append(('integrity', id(self)))
            return super().check_integrity()
        def read(self, **kwargs):
            calls.append(('read', id(self), kwargs))
            return super().read(**kwargs)
    monkeypatch.setattr(fit, 'Decoder', TrackingDecoder)
    decoded = fit.decode_fit(build_synthetic_fit())
    assert decoded.stream.sample_count == 588
    assert len(instances) == 3
    explicit = [item for item in calls if item[0] in {'integrity', 'read'}]
    assert len({item[1] for item in explicit}) == 2
    assert calls[0][0] == 'is_fit'
    assert calls[0][1] not in {item[1] for item in explicit}
    assert explicit[-1][2] == {'apply_scale_and_offset': True,
        'convert_datetimes_to_dates': False, 'convert_types_to_strings': True,
        'expand_sub_fields': False, 'expand_components': True}


def test_sdk_read_failure_is_decode_failed(monkeypatch):
    from garmin_fit_sdk import Decoder as SDKDecoder

    from app.adapters.garmin import fit

    monkeypatch.setattr(SDKDecoder, 'read', lambda self, **_: ({}, ['synthetic error']))
    _code(lambda: fit.decode_fit(build_synthetic_fit()), 'decode_failed')
    def broken(self, **_):
        raise RuntimeError('synthetic SDK error')
    monkeypatch.setattr(SDKDecoder, 'read', broken)
    _code(lambda: fit.decode_fit(build_synthetic_fit()), 'decode_failed')


def test_declared_and_streamed_size_limit(monkeypatch):
    from app.adapters.garmin import fit
    archive = build_synthetic_zip({'synthetic.fit': b'12345'})
    monkeypatch.setattr(fit, 'MAX_FIT_BYTES', 4)
    _code(lambda: extract_fit(archive), 'zip_member_too_large')
    # A reader can return more bytes than the declared ZIP member size.
    class MismatchedArchive:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def infolist(self): return [SimpleNamespace(filename='synthetic.fit', file_size=1, is_dir=lambda: False)]
        def open(self, *_): return io.BytesIO(b'12345')
    monkeypatch.setattr(fit.zipfile, 'ZipFile', lambda *_: MismatchedArchive())
    _code(lambda: extract_fit(archive), 'zip_member_too_large')


def test_missing_ambiguous_session_and_stream_variants(monkeypatch):
    from garmin_fit_sdk import Decoder as SDKDecoder
    from garmin_fit_sdk import Stream

    from app.adapters.garmin import fit
    original = SDKDecoder.read
    payload = build_synthetic_fit()
    messages, errors = SDKDecoder(Stream.from_byte_array(bytearray(payload))).read(
        convert_datetimes_to_dates=False, expand_sub_fields=False, convert_types_to_strings=True)
    assert not errors
    def inject(changes):
        modified = copy.deepcopy(messages)
        changes(modified)
        monkeypatch.setattr(fit.Decoder, 'read', lambda self, **_: (modified, []))
        return fit.decode_fit(payload)
    _code(lambda: inject(lambda m: m.update(session_mesgs=[])), 'missing_session')
    _code(lambda: inject(lambda m: m['session_mesgs'].append(m['session_mesgs'][0])), 'ambiguous_session')
    _code(lambda: inject(lambda m: m['session_mesgs'][0].pop('start_time')), 'missing_start')
    def fractional(m):
        m['record_mesgs'][0] = {**m['record_mesgs'][0], 'timestamp': START_FIT_TS + .5}
    _code(lambda: inject(fractional), 'invalid_stream_time')
    def variants(m):
        first = dict(m['record_mesgs'][0])
        first.pop('enhanced_speed')
        first['speed'] = 2.5
        m['record_mesgs'][0] = first
        second = dict(first, heart_rate=180)
        third = dict(first)
        m['record_mesgs'].extend([second, third])
        m['event_mesgs'] = []
    decoded = inject(variants)
    assert decoded.stream.speed_mps[0] == 2.5
    assert decoded.stream.hr_bpm[0] is None
    assert 'DUPLICATE_RECORD_CONFLICT' in decoded.stream.quality_flags
    assert decoded.stream.timer_on == ()
    assert 'TIMER_EVENTS_MISSING' in decoded.stream.quality_flags
    def inferred(m):
        m['event_mesgs'] = [item for item in m['event_mesgs'] if item['event_type'] == 'start'][:1]
    decoded = inject(inferred)
    assert decoded.stream.timer_on == ((0, 600),)
    assert {'TIMER_END_INFERRED', 'TIMER_MISMATCH'} <= set(decoded.stream.quality_flags)
    def absent_records(m):
        m['record_mesgs'] = []
    decoded = inject(absent_records)
    assert decoded.stream.sample_count == 0 and decoded.stream.max_gap_s == 0
    assert decoded.stream.t_s == ()
    def ambiguous(m):
        m['event_mesgs'] = [m['event_mesgs'][0], m['event_mesgs'][0]]
    decoded = inject(ambiguous)
    assert decoded.stream.timer_on == ()
    assert 'TIMER_EVENTS_AMBIGUOUS' in decoded.stream.quality_flags
    def adjacent(m):
        m['event_mesgs'] = [m['event_mesgs'][0],
            {'timestamp': START_FIT_TS + 300, 'event': 'timer', 'event_type': 'stop'},
            {'timestamp': START_FIT_TS + 300, 'event': 'timer', 'event_type': 'start'},
            m['event_mesgs'][-1]]
    decoded = inject(adjacent)
    assert decoded.stream.timer_on == ((0, 600),)
    def trail(m):
        m['session_mesgs'][0]['sub_sport'] = 'trail'
    assert inject(trail).session.sport == 'trail_running'
    def treadmill(m):
        m['session_mesgs'][0]['sub_sport'] = 'treadmill'
    assert inject(treadmill).session.sport == 'treadmill_running'
    monkeypatch.setattr(fit.Decoder, 'read', original)


def test_wrappers_use_call_and_check_download_shape(monkeypatch):
    source = GarminPersonalSource(Path('/unused'), Path('/unused'))
    calls = []
    source._client = SimpleNamespace(download_activity=lambda id: b'zip',
        get_activity_workouts=lambda id: {'id': id}, get_activity=lambda id: {'id': id})
    monkeypatch.setattr(source, '_call', lambda operation: (calls.append(True), operation())[1])
    assert source.download_activity('1') == b'zip'
    assert source.activity_workouts('2') == {'id': '2'}
    assert source.activity_detail('3') == {'id': '3'}
    assert len(calls) == 3
    source._client.download_activity = lambda id: {'bad': True}
    with pytest.raises(GarminConfigurationError, match='invalid_fit_download_shape'):
        source.download_activity('4')
