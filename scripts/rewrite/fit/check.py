"""Run from the repository root with uv run --project backend python path/to/check.py."""

import json
import runpy
import subprocess
import tempfile
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

SOURCE = Path(__file__).resolve().parent
PRIVATE_FIELDS = {"position_lat", "position_long", "serial_number"}


def fallback_fixture(writer, start):
    writer.define(0, 18, [(2, 4, 0x86), (5, 1, 0x00), (6, 1, 0x00), (7, 4, 0x86)])
    writer.data(0, start, 1, 3, 12000)
    writer.define(1, 20, [(253, 4, 0x86), (3, 1, 0x02), (6, 2, 0x84), (2, 2, 0x84)])
    writer.data(1, start, 100, 2100, 2550)
    writer.data(1, start, 110, 2100, 2550)
    writer.data(1, start + 12, 255, 65535, 65535)
    return writer.finish()


def reference(data):
    def decoder():
        return Decoder(Stream.from_byte_array(bytearray(data)))

    if not decoder().is_fit():
        return {"error": "invalid_fit"}
    if not decoder().check_integrity():
        return {"error": "invalid_crc"}
    messages, errors = decoder().read(
        apply_scale_and_offset=True,
        convert_datetimes_to_dates=False,
        convert_types_to_strings=False,
        expand_sub_fields=False,
        expand_components=True,
    )
    assert not errors, errors
    rows = {
        name: [
            {k: v for k, v in row.items() if k not in PRIVATE_FIELDS} for row in group
        ]
        for name, group in messages.items()
    }
    return {"profile": int.from_bytes(data[2:4], "little"), "messages": rows}


def check():
    fixture = runpy.run_path("backend/tests/fixtures/fit/synthetic.py")
    normal = fixture["build_synthetic_fit"]()
    cases = {
        "structured run with pause, laps, RPE, speed and HR targets": normal,
        "duplicate HR, fallback speed/altitude, invalid sentinels": fallback_fixture(
            fixture["_Writer"](), fixture["START_FIT_TS"]
        ),
        "CRC mismatch": normal[:-1] + bytes([normal[-1] ^ 1]),
        "invalid FIT": b"bad",
    }
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory) / "fitprobe"
        subprocess.run(
            ["go", "build", "-mod=readonly", "-o", binary, "."], cwd=SOURCE, check=True
        )
        for label, data in cases.items():
            actual = json.loads(subprocess.check_output([binary], input=data))
            expected = reference(data)
            assert actual.keys() == expected.keys(), label
            for k in expected:
                if k != "messages":
                    assert actual[k] == expected[k], (label, k, actual[k], expected[k])
                    continue
                assert actual[k].keys() == expected[k].keys(), label
                for name, rows in expected[k].items():
                    for i, (got, want) in enumerate(
                        zip(actual[k][name], rows, strict=True)
                    ):
                        assert got == want, (label, name, i, got, want)
            print("PASS", label)


if __name__ == "__main__":
    check()
