"""Compare DecodeZIP with decode_fit_zip on deterministic synthetic archives.

Run with uv run --project backend python scripts/rewrite/fit/check_normalized.py.
Pass --update to refresh the fixtures after reviewing a reference change.
"""

import argparse
import base64
import io
import json
import struct
import subprocess
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "backend-go/internal/garmin/fit"
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests/fixtures/fit")]
from app.adapters.garmin.fit import FitDecodeError, decode_fit_zip
from synthetic import LAT_CANARY, START_FIT_TS, _Writer, build_synthetic_fit


def archive(*members, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, data in members:
            entry = zipfile.ZipInfo(name)  # fixed DOS epoch
            entry.compress_type = compression
            entry.create_system = 3
            zipped.writestr(entry, data)
    return output.getvalue()


def activity(scenario):
    w = _Writer()
    start = START_FIT_TS
    w.define(0, 18, [(2, 4, 0x86), (5, 1, 0), (6, 1, 0), (7, 4, 0x86), (8, 4, 0x86)])
    for _ in range({"missing_session": 0, "ambiguous_session": 2}.get(scenario, 1)):
        w.data(
            0, 0xFFFFFFFF if scenario == "missing_start" else start, 1, 3, 12000, 8000
        )
    w.define(
        1, 23, [(2, 2, 0x84), (3, 4, 0x8C), (4, 2, 0x84), (5, 2, 0x84), (27, 24, 7)]
    )
    w.data(1, 1, 987654321, 1234, 1834, "synthetic-device-canary")
    if scenario in {"channels", "invalid_stream_time"}:
        w.define(
            2, 20, [(253, 4, 0x86), (3, 1, 2), (6, 2, 0x84), (2, 2, 0x84), (1, 4, 0x85)]
        )
        w.data(2, start + 12, 255, 65535, 65535, -LAT_CANARY)
        for hr in [100, 110, 100]:
            w.data(
                2,
                start - 1 if scenario == "invalid_stream_time" else start,
                hr,
                2100,
                2501,
                -LAT_CANARY,
            )
        w.define(3, 19, [(253, 4, 0x86), (7, 4, 0x86), (23, 1, 0), (13, 2, 0x84)])
        w.data(3, start + 10, 5250, 2, 2333)
        w.data(3, 0xFFFFFFFF, 0xFFFFFFFF, 1, 0xFFFF)
        w.define(4, 27, [(254, 2, 0x84), (1, 1, 0)])
        for index in [3, 0, 2]:
            w.data(4, index, 5)
    if scenario in {"inferred_timer", "ambiguous_timer"}:
        w.define(5, 21, [(253, 4, 0x86), (0, 1, 0), (1, 1, 0)])
        w.data(5, start, 0, 0)
        if scenario == "ambiguous_timer":
            w.data(5, start + 1, 0, 0)
    if scenario == "decode_failed":
        w.define(6, 27, [(1, 1, 0)])
        w.data(6, 5)
    return w.finish()


def running_session():
    w = _Writer()
    w.define(0, 18, [(2, 4, 0x86), (5, 1, 0)])
    w.data(0, START_FIT_TS, 1)
    return w


def sdk_cases():
    yield "empty_fit", _Writer().finish()
    w = running_session()
    w.define(1, 20, [(253, 4, 0x86), (5, 8, 0x86)])
    # Two uint32 distance samples, one with the FIT invalid sentinel.
    w.data(1, START_FIT_TS, (125, 0xFFFFFFFF))
    yield "mixed_distance_array", w.finish()
    w = running_session()
    w.define(1, 206, [(1, 1, 2), (2, 1, 2)])
    w.data(1, 0, 2)
    yield "field_description_without_index", w.finish()
    w = running_session()
    w.define(1, 207, [(2, 2, 0x84)])
    w.data(1, 1)
    yield "developer_data_without_index", w.finish()
    w = running_session()
    w.define(1, 20, [(253, 4, 0x86), (8, 3, 0x0D)])
    # Two 12-bit little-endian components. Distance has finer resolution than centimetres.
    packed = (17 << 12) | 213
    w.data(1, START_FIT_TS, packed.to_bytes(3, "little"))
    yield "packed_speed_distance", w.finish()
    w = running_session()
    yield "concatenated_fits", w.finish() * 2
    yield "trailing", w.finish() + b"\x00"
    w.define(1, 20, [(253, 4, 0x86), (200, 2, 0x84)])
    w.data(1, START_FIT_TS, 42)
    w.define(2, 500, [(0, 2, 0x84)])
    w.data(2, 35)
    yield "unknown_fields_and_messages", w.finish()
    w = running_session()
    w.define(1, 20, [(253, 4, 0x86), (3, 1, 2)])
    w.data(1, START_FIT_TS, 80)
    w.data(1, START_FIT_TS + 1, 81)
    w.define(2, 132, [(253, 4, 0x86), (0, 2, 0x84), (6, 1, 2), (9, 4, 0x86)])
    for i, hr in enumerate((120, 121, 122)):
        w.data(2, START_FIT_TS + i, 0, hr, 1024 * (i + 1))
    yield "merged_hr", w.finish()
    w = running_session()
    w.define(1, 20, [(253, 4, 0x86), (3, 1, 2)])
    w.data(1, START_FIT_TS, 80)
    w.define(1, 20, [(3, 1, 2)])
    w.body.extend(bytes([0x80 | (1 << 5) | ((START_FIT_TS + 1) & 0x1F), 81]))
    yield "compressed_timestamp", w.finish()
    w = running_session()
    w.define(2, 19, [(23, 1, 0)])
    yield "definition_only", w.finish()
    w = running_session()
    w.define(2, 19, [(2, 4, 0x86), (24, 1, 0), (23, 1, 0)])
    w.data(2, START_FIT_TS, 199, 199)
    w.define(3, 27, [(254, 2, 0x84), (1, 1, 0), (3, 1, 0), (7, 1, 0)])
    w.data(3, 1, 199, 199, 199)
    yield "unknown_enums", w.finish()


def cases():
    for name, payload in sdk_cases():
        yield name, archive(("synthetic.fit", payload))
    structured = build_synthetic_fit()
    yield (
        "structured",
        archive(
            ("ignored.fit/", b""), ("note.txt", b"ok"), ("nested/RUN.FIT", structured)
        ),
    )
    for scenario in (
        "channels",
        "inferred_timer",
        "ambiguous_timer",
        "missing_session",
        "ambiguous_session",
        "missing_start",
        "invalid_stream_time",
        "decode_failed",
    ):
        yield scenario, archive(("activity.fit", activity(scenario)))
    yield "zero_members", archive(("notes.txt", b"x"))
    yield "multiple_members", archive(("one.fit", b"x"), ("two.FIT", b"x"))
    yield "invalid_fit", archive(("invalid.fit", b"bad"))
    minimal = running_session().finish()
    yield (
        "invalid_crc",
        archive(("corrupt.fit", minimal[:-1] + bytes([minimal[-1] ^ 1]))),
    )
    yield "bad_zip", b"broken archive"
    yield (
        "deflated",
        archive(("run.fit", minimal), compression=zipfile.ZIP_DEFLATED),
    )
    yield "bzip2", archive(("run.fit", minimal), compression=zipfile.ZIP_BZIP2)
    small = archive(("small.fit", b"unique payload"))
    yield "bad_member_crc", small.replace(b"unique payload", b"broken payload")
    oversized = bytearray(small)
    struct.pack_into(
        "<I", oversized, oversized.index(b"PK\x01\x02") + 24, 50 * 1024 * 1024 + 1
    )
    yield "oversized", bytes(oversized)


def timestamp(value):
    if isinstance(value, datetime):
        utc = value.isoformat().removesuffix("+00:00")
        return (utc.rstrip("0") if "." in utc else utc) + "Z"
    raise TypeError(type(value))


def reference(name, data):
    case = {"name": name, "archive": base64.b64encode(data).decode()}
    try:
        case["decoded"] = asdict(decode_fit_zip(data))
    except FitDecodeError as exc:
        case["error"] = exc.code
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    golden = PACKAGE / "testdata/normalized.json"
    result = (
        "[\n"
        + ",\n".join(
            json.dumps(
                reference(name, data),
                sort_keys=True,
                default=timestamp,
                separators=(",", ":"),
            )
            for name, data in cases()
        )
        + "\n]\n"
    )
    if args.update:
        golden.write_text(result)
    elif result != golden.read_text():
        sys.exit("Reference fixtures changed. Run with --update and inspect the diff.")
    subprocess.run(
        ["go", "test", "-count=1", "-run", "^TestNormalizedParity$", "."],
        cwd=PACKAGE,
        check=True,
    )


if __name__ == "__main__":
    main()
