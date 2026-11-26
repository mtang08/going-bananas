"""Rebuild Strong CSV fixtures with the Python adapter, then check the native parser."""

import argparse
import csv
import io
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.adapters.strong import COLUMNS, StrongCSVError, scan_strong_csv

GOLDEN = ROOT / "backend-go/internal/strong/testdata/scan.json"


def csv_text(rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return out.getvalue()


def cases():
    row = ["2026-11-09 21:13:58", 'Upper "A" <左右> & café', "1h 5m", "Press, dumbbell\r\nbench", "1", "45.0", "8", "0", "0", ""]
    def change(**fields):
        result = list(row)
        for field, value in fields.items():
            result[COLUMNS.index(field)] = value
        return result
    yield "bom-grouped-sets", "\ufeff" + csv_text([row, change(**{"Date": "2026-11-8 1:2:3", "Duration": "120h 41m", "Set Order": "W"}), change(**{"Set Order": "F", "Weight": "0_5.0", "RPE": "1e0"})])
    yield "unicode-source-spellings", csv_text([change(Date="２０２６-1- 1 ١:١:٢", Duration="１h\u2009５m", Weight="４５.０")])
    yield "unknown-and-boundary-duration", csv_text([change(Duration=""),change(Date="2026-11-10 00:00:00", Duration="24h")])
    yield "empty", csv_text([])
    yield "wrong-columns", "Date,Workout\n"
    for code, rows in [
        ("malformed_row", [row[:-1]]), ("invalid_date", [change(Date="2026-02-30 10:00:00")]),
        ("missing_name", [change(**{"Workout Name": " "})]), ("invalid_number", [change(Reps="NaN")]),
        ("invalid_set_order", [change(**{"Set Order": "100"})]), ("invalid_duration", [change(Duration="6 mins")]),
        ("inconsistent_duration", [row,change(Duration="5m")]),
    ]:
        yield code, csv_text(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    fixtures = []
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as directory:
        path = Path(directory) / "synthetic.csv"
        for name, source in cases():
            path.write_bytes(source.encode())
            case = {"name": name, "csv": source}
            try:
                workouts, digest, _ = scan_strong_csv(path)
                case.update(workouts=[asdict(item) for item in workouts], digest=digest)
            except StrongCSVError as exc:
                case["error"] = str(exc)
            fixtures.append(case)
    encoded = json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n"
    if args.update:
        GOLDEN.write_text(encoded)
    elif GOLDEN.read_text() != encoded:
        raise SystemExit("Strong CSV reference has changed")
    subprocess.run(["go", "test", "-count=1", "-race", "./internal/strong"], cwd=ROOT / "backend-go", check=True)
    print(f"{len(fixtures)} Strong CSV parity cases")


if __name__ == "__main__":
    main()
