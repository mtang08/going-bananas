"""Run the native recovery PostgreSQL cases."""

from training_fixture import check_cases, seed_recovery

if __name__ == "__main__":
    check_cases(
        "internal/metrics/recovery",
        "recovery.json.gz",
        "RECOVERY_CASES",
        "TestRecoveryPostgres",
        seed_recovery,
    )
