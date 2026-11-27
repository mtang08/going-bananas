"""Run the native self reports PostgreSQL cases."""

from training_fixture import check_cases, seed_self_reports

if __name__ == "__main__":
    check_cases(
        "internal/calendar",
        "self-reports.json",
        "COMPLETION_CASES",
        "TestSelfReportsPostgres",
        seed_self_reports,
    )
