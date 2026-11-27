"""Exercise metric command receipts, retry behavior, and persisted state."""

from check_health_startup import run_database_test
from training_fixture import seed_assessment

if __name__ == "__main__":
    run_database_test("./internal/metriccli", seed_assessment)
