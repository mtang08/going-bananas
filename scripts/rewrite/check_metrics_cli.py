"""Exercise metric command receipts, retry behavior, and persisted state."""

from training_fixture import seed_assessment
from check_health_startup import run_database_test


if __name__ == "__main__":
    run_database_test("./internal/metriccli", seed_assessment)
