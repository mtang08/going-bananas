"""Run the native aerobic PostgreSQL cases."""

from training_fixture import check_cases, seed_runs

if __name__ == "__main__":
    check_cases(
        "internal/metrics/trainingwindows",
        "windows.json.gz",
        "AEROBIC_CASES",
        "TestAerobicWindowsPostgres",
        seed_runs,
    )
